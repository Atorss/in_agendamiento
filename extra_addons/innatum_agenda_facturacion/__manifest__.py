# -*- coding: utf-8 -*-
{
    'name': 'Innatum Agenda Facturación',
    'summary': 'Facturación de turnos: producto por servicio + Pedido de venta + factura electrónica EC',
    'description': """
        Módulo opcional de facturación para Innatum Agenda.

        Funciones:
        - Cada innatum.agenda.servicio queda vinculado a un product.product
          de tipo servicio (auto-creado al guardar el servicio).
        - El precio se gestiona desde el servicio y se sincroniza con el producto.
        - Botón "Facturar" en la ficha del turno crea una sale.order con la
          línea del servicio asociado.
        - Solo Operador y Administrador pueden facturar.
        - Al instalar este módulo se incorpora la stack contable + EDI Ecuador.
    """,
    'author': 'Innatum',
    'website': 'https://www.innatum.com',
    'category': 'Services',
    'version': '18.0.1.2.0',
    'depends': [
        'innatum_agenda_core',
        'innatum_agenda_admin',
        'sale_management',
        'l10n_ec_edi',
        'muk_web_appsbar',
    ],
    'data': [
        'security/innatum_agenda_facturacion_groups.xml',
        'security/ir.model.access.csv',
        'security/innatum_agenda_facturacion_rules.xml',
        'wizard/wizard_crear_producto_views.xml',
        'views/hr_employee_views.xml',
        'views/innatum_agenda_servicio_views.xml',
        'views/innatum_agenda_turno_views.xml',
        'views/res_company_views.xml',
        'views/account_move_views.xml',
        'views/innatum_agenda_facturacion_menus.xml',
        'data/menu_groups_wiring.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
    'post_init_hook': '_post_init_crear_productos',
}
