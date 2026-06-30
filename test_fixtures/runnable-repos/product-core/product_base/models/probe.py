from odoo import fields, models


class ProductProbe(models.Model):
    """A trivial model that a second repo inherits and overrides.

    The smoke test asserts that ``greet()`` returns ``"core"`` from this repo
    alone, and ``"ext+core"`` once product-ext's override is on the addons_path
    — proving cross-repo _inherit + method override + super() all resolve.
    """

    _name = "product.probe"
    _description = "Product Probe (smoke fixture)"

    name = fields.Char(required=True)

    def greet(self):
        self.ensure_one()
        return "core"
