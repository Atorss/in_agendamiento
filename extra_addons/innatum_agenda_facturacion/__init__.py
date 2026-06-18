from . import models
from . import wizard


def _post_init_crear_productos(env):
    """Al instalar el módulo, crea productos para los servicios existentes
    que aún no tengan un product_id vinculado."""
    servicios = env['innatum.agenda.servicio'].search([('product_id', '=', False)])
    for servicio in servicios:
        servicio._crear_producto()
