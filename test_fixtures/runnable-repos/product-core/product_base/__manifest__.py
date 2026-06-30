{
    "name": "Product Base",
    "version": "19.0.1.0.0",
    "summary": "Smoke fixture: defines product.probe (the base model an over-repo override targets)",
    "depends": ["base"],
    "data": [
        "security/ir.model.access.csv",
        "views/probe_views.xml",
    ],
    "installable": True,
    "auto_install": False,
}
