"""
live/  Flux de transactions brutes MoMTSim (Kafka + REST).

Ce package est additif : il importe le moteur de simulation existant
(src/momtsim_torch.py) sans le modifier ni le dupliquer, et n'ajoute aucune
route au backend FastAPI du mémoire (backend/api.py reste dédié au
calibrage et aux figures).
"""
