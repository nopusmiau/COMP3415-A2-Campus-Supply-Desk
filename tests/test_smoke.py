"""A small starting test suite for the order desk."""

from pathlib import Path
import tempfile
import unittest

from supplydesk.service import OrderService


class OrderSmokeTests(unittest.TestCase):
    def setUp(self):
        self.directory = tempfile.TemporaryDirectory()
        self.addCleanup(self.directory.cleanup)
        self.path = Path(self.directory.name) / "state.json"
        self.service = OrderService(self.path)

    def test_regular_pickup_quote(self):
        quote = self.service.quote("regular", [{"product_id": "notebook", "quantity": 2}])
        self.assertEqual(quote["subtotal_cents"], 1000)
        self.assertEqual(quote["discount_cents"], 0)
        self.assertEqual(quote["delivery_cents"], 0)
        self.assertEqual(quote["total_cents"], 1000)

    def test_student_delivery_quote(self):
        quote = self.service.quote("student", [{"product_id": "hoodie", "quantity": 2}], "delivery")
        self.assertEqual(quote["discount_cents"], 800)
        self.assertEqual(quote["delivery_cents"], 600)
        self.assertEqual(quote["total_cents"], 7800)

    def test_order_can_be_reopened(self):
        order = self.service.place_order("regular", [{"product_id": "mug", "quantity": 1}])
        self.assertEqual(order["order_id"], "ORD-0001")
        self.assertEqual(order["status"], "placed")
        self.assertEqual(OrderService(self.path).get_order(order["order_id"]), order)

    def test_cancel_order_restores_stock(self):
        before = self.service.catalog()
        order = self.service.place_order("regular", [{"product_id": "pen-pack", "quantity": 2}])
        cancelled = self.service.cancel_order(order["order_id"])
        self.assertEqual(cancelled["status"], "cancelled")
        self.assertEqual(self.service.catalog(), before)

    def test_place_order_records_history_and_stock_changes(self):
        """Normal behavior: a valid order is saved with the expected ID and reduces stock."""
        order = self.service.place_order("regular", [{"product_id": "notebook", "quantity": 2}])

        self.assertEqual(order["order_id"], "ORD-0001")
        self.assertEqual(order["status"], "placed")
        self.assertEqual(order["total_cents"], 1000)
        self.assertEqual(self.service.catalog()[0]["stock"], 18)
        self.assertEqual(self.service.list_orders(), [order])

    def test_empty_collection_and_zero_quantity_are_rejected(self):
        """Boundary behavior: empty collections and quantities below the minimum are invalid."""
        with self.assertRaisesRegex(ValueError, "at least one item"):
            self.service.quote("regular", [])

        with self.assertRaisesRegex(ValueError, "Quantity must be an integer from 1 to 99"):
            self.service.quote("regular", [{"product_id": "notebook", "quantity": 0}])

    def test_invalid_request_does_not_change_saved_state(self):
        """Invalid behavior: bad input must raise ValueError without mutating the store."""
        before = self.service.store.load()

        with self.assertRaisesRegex(ValueError, "Unknown product"):
            self.service.place_order("regular", [{"product_id": "ghost-item", "quantity": 1}])

        self.assertEqual(self.service.store.load(), before)
        self.assertEqual(self.service.list_orders(), [])

    def test_quote_does_not_reserve_stock_and_cancellation_restores_it(self):
        """Important preserved behavior: quotes are read-only, and cancellation restores stock."""
        before_quote = self.service.catalog()
        quote = self.service.quote("regular", [{"product_id": "mug", "quantity": 1}])

        self.assertEqual(quote["total_cents"], 1500)
        self.assertEqual(self.service.catalog(), before_quote)

        order = self.service.place_order("regular", [{"product_id": "mug", "quantity": 1}])
        cancelled = self.service.cancel_order(order["order_id"])

        self.assertEqual(cancelled["status"], "cancelled")
        self.assertEqual(self.service.catalog(), before_quote)

    def test_cancelled_order_stays_in_history_and_next_order_number_advances(self):
        """Important preserved behavior: cancelled orders remain recorded and IDs are never reused."""
        first = self.service.place_order("regular", [{"product_id": "mug", "quantity": 1}])
        self.service.cancel_order(first["order_id"])

        second = self.service.place_order("regular", [{"product_id": "notebook", "quantity": 1}])

        self.assertEqual(first["order_id"], "ORD-0001")
        self.assertEqual(second["order_id"], "ORD-0002")
        self.assertEqual(len(self.service.list_orders()), 2)
        self.assertEqual(self.service.list_orders()[0]["status"], "cancelled")
        self.assertEqual(self.service.list_orders()[1]["status"], "placed")
    
    def test_express_delivery_quote_regular(self):
        # 2 notebooks ($10.00) + express ($12.00) = $22.00 (2200 cents)
        quote = self.service.quote("regular", [{"product_id": "notebook", "quantity": 2}], "express")
        self.assertEqual(quote["subtotal_cents"], 1000)
        self.assertEqual(quote["discount_cents"], 0)
        self.assertEqual(quote["delivery_cents"], 1200)
        self.assertEqual(quote["total_cents"], 2200)

    def test_express_delivery_quote_student(self):
        # 2 hoodies ($80.00) - 10% student discount ($8.00) + express ($12.00) = $84.00 (8400 cents)
        quote = self.service.quote("student", [{"product_id": "hoodie", "quantity": 2}], "express")
        self.assertEqual(quote["subtotal_cents"], 8000)
        self.assertEqual(quote["discount_cents"], 800)
        self.assertEqual(quote["delivery_cents"], 1200)
        self.assertEqual(quote["total_cents"], 8400)
    
    def test_express_delivery_not_waived_for_high_subtotal(self):
        # 3 hoodies ($120.00) with standard delivery is free ($120.00 / 12000 cents)
        standard_quote = self.service.quote("regular", [{"product_id": "hoodie", "quantity": 3}], "delivery")
        self.assertEqual(standard_quote["delivery_cents"], 0)
        self.assertEqual(standard_quote["total_cents"], 12000)

        # 3 hoodies ($120.00) with express delivery fee is NOT waived ($132.00 / 13200 cents)
        express_quote = self.service.quote("regular", [{"product_id": "hoodie", "quantity": 3}], "express")
        self.assertEqual(express_quote["delivery_cents"], 1200)
        self.assertEqual(express_quote["total_cents"], 13200)
    
    def test_place_and_cancel_express_order(self):
        order = self.service.place_order("student", [{"product_id": "hoodie", "quantity": 2}], "express")
        self.assertEqual(order["fulfillment"], "express")
        self.assertEqual(order["total_cents"], 8400)
        
        # Verify persistence and retrieval
        reopened = self.service.get_order(order["order_id"])
        self.assertEqual(reopened["fulfillment"], "express")
        self.assertEqual(reopened["total_cents"], 8400)
        
        # Verify cancellation behavior is preserved
        cancelled = self.service.cancel_order(order["order_id"])
        self.assertEqual(cancelled["status"], "cancelled")
        self.assertEqual(cancelled["fulfillment"], "express")


if __name__ == "__main__":
    unittest.main()
