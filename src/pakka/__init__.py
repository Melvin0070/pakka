import os

# The project was called Pramaan; hosted deployments and old shells still set PRAMAAN_* variables.
for _k, _v in list(os.environ.items()):
    if _k.startswith("PRAMAAN_"):
        os.environ.setdefault("PAKKA_" + _k[len("PRAMAAN_") :], _v)
