# Cross-repo inherit/override smoke. Run via:
#     owm shell <instance> --script test_fixtures/runnable-repos/smoke_inherit.py --json
# odoo-bin shell exposes `env`; this emits one NDJSON row per check (case/status),
# matching owm's run-script convention so OK/FAIL is greppable.
import json

probe = env["product.probe"].create({"name": "x", "extra": "y"})

checks = [
    # product_base loaded from the product-core repo
    ("model_registered", "product.probe" in env.registry),
    # field merged in from the product-ext repo's _inherit
    ("cross_repo_field", "extra" in probe._fields),
    # method override + super() chained across the repo boundary
    ("cross_repo_override", probe.greet() == "ext+core"),
    # view inheritance: ext view extends the base view via inherit_id
    (
        "view_inherit",
        (lambda b, e: bool(b and e and e.inherit_id == b))(
            env.ref("product_base.view_product_probe_form", raise_if_not_found=False),
            env.ref("product_ext.view_product_probe_form_ext", raise_if_not_found=False),
        ),
    ),
]

for case, ok in checks:
    print(json.dumps({"case": case, "status": "OK" if ok else "FAIL"}))

env.cr.rollback()
