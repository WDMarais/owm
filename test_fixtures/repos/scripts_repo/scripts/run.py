# Minimal script fixture — no Odoo dependency, plain Python
import json, sys

cases = [
    {"case": "check_a", "status": "OK"},
    {"case": "check_b", "status": "OK"},
]
for row in cases:
    print(json.dumps(row))
sys.exit(0)
