"""Operations used by the command-line order desk."""

from supplydesk.storage import JsonStore


class OrderService:
    STUDENT_DISCOUNT_THRESHOLD_CENTS = 5000
    STUDENT_DISCOUNT_RATE_PERCENT = 10
    DELIVERY_FEE_CENTS = 600
    EXPRESS_DELIVERY_FEE_CENTS = 1200
    FREE_DELIVERY_THRESHOLD_CENTS = 10000
    MIN_QUANTITY = 1
    MAX_QUANTITY = 99

    def __init__(self, state_path=".supplydesk/state.json"):
        self.store = JsonStore(state_path)

    def catalog(self):
        return self.store.load()["catalog"]

    def _find_product(self, catalog, product_id):
        for candidate in catalog:
            if candidate["product_id"] == product_id:
                return candidate
        return None

    def _calculate_discount(self, customer_type, subtotal):
        if customer_type == "student" and subtotal > self.STUDENT_DISCOUNT_THRESHOLD_CENTS:
            return (subtotal * self.STUDENT_DISCOUNT_RATE_PERCENT + 50) // 100
        return 0

    def _calculate_delivery(self, fulfillment, subtotal, discount):
        if fulfillment == "pickup":
            return 0
        if fulfillment == "express":
            return self.EXPRESS_DELIVERY_FEE_CENTS
        if fulfillment == "delivery":
            if subtotal - discount >= self.FREE_DELIVERY_THRESHOLD_CENTS:
                return 0
            return self.DELIVERY_FEE_CENTS
        return 0

    def _validate_and_build_lines(self, state, customer_type, items, fulfillment):
        if customer_type not in ("regular", "student"):
            raise ValueError("Customer type must be regular or student.")
        if fulfillment not in ("pickup", "delivery", "express"):
            raise ValueError("Fulfillment must be pickup, delivery or express.")
        if not isinstance(items, list) or not items:
            raise ValueError("An order must contain at least one item.")

        lines = []
        subtotal = 0
        for item in items:
            if not isinstance(item, dict):
                raise ValueError("Each item must contain a product_id and quantity.")
            product = self._find_product(state["catalog"], item.get("product_id"))
            if product is None:
                raise ValueError("Unknown product.")

            quantity = item.get("quantity")
            if type(quantity) is not int or quantity < self.MIN_QUANTITY or quantity > self.MAX_QUANTITY:
                raise ValueError("Quantity must be an integer from 1 to 99.")
            if quantity > product["stock"]:
                raise ValueError("Not enough stock for " + product["product_id"] + ".")

            line_total = product["unit_price_cents"] * quantity
            subtotal += line_total
            lines.append({
                "product_id": product["product_id"],
                "name": product["name"],
                "unit_price_cents": product["unit_price_cents"],
                "quantity": quantity,
                "line_total_cents": line_total,
            })

        discount = self._calculate_discount(customer_type, subtotal)
        delivery = self._calculate_delivery(fulfillment, subtotal, discount)
        return {
            "items": lines,
            "subtotal_cents": subtotal,
            "discount_cents": discount,
            "delivery_cents": delivery,
            "total_cents": subtotal - discount + delivery,
        }

    def quote(self, customer_type, items, fulfillment="pickup"):
        state = self.store.load()
        order_totals = self._validate_and_build_lines(state, customer_type, items, fulfillment)
        return {
            "customer_type": customer_type,
            "fulfillment": fulfillment,
            "items": order_totals["items"],
            "subtotal_cents": order_totals["subtotal_cents"],
            "discount_cents": order_totals["discount_cents"],
            "delivery_cents": order_totals["delivery_cents"],
            "total_cents": order_totals["total_cents"],
        }

    def place_order(self, customer_type, items, fulfillment="pickup"):
        state = self.store.load()
        order_totals = self._validate_and_build_lines(state, customer_type, items, fulfillment)
        order = {
            "order_id": "ORD-" + str(state["next_order_number"]).zfill(4),
            "status": "placed",
            "customer_type": customer_type,
            "fulfillment": fulfillment,
            "items": order_totals["items"],
            "subtotal_cents": order_totals["subtotal_cents"],
            "discount_cents": order_totals["discount_cents"],
            "delivery_cents": order_totals["delivery_cents"],
            "total_cents": order_totals["total_cents"],
        }
        for line in order_totals["items"]:
            product = self._find_product(state["catalog"], line["product_id"])
            product["stock"] -= line["quantity"]
        state["next_order_number"] += 1
        state["orders"].append(order)
        self.store.save(state)
        return order

    def list_orders(self):
        return self.store.load()["orders"]

    def get_order(self, order_id):
        state = self.store.load()
        for order in state["orders"]:
            if order["order_id"] == order_id:
                return order
        raise ValueError("Unknown order: " + order_id)

    def cancel_order(self, order_id):
        state = self.store.load()
        order = None
        for candidate in state["orders"]:
            if candidate["order_id"] == order_id:
                order = candidate
                break
        if order is None:
            raise ValueError("Unknown order: " + order_id)
        for line in order["items"]:
            product = self._find_product(state["catalog"], line["product_id"])
            product["stock"] += line["quantity"]
        order["status"] = "cancelled"
        self.store.save(state)
        return order
