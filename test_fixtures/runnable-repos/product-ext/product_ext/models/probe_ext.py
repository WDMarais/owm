from odoo import fields, models


class ProductProbe(models.Model):
    """Extend product.probe (defined in the product-core repo).

    Adds a field and chains the method via super(), so a passing smoke test
    proves the override resolved across the repo boundary rather than shadowing.
    """

    _inherit = "product.probe"

    extra = fields.Char()

    def greet(self):
        return "ext+" + super().greet()
