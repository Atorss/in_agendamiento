# -*- coding: utf-8 -*-
{
    'name': 'Innatum Agenda - Sitio Web',
    'summary': 'Portal web para que los clientes agenden citas en línea',
    'description': """
        Innatum Agenda Web — Formulario público para agendar citas:
        - Página principal con directorio de profesionales
        - Selección de servicio, profesional y horario disponible
        - Registro de datos del cliente
        - Reserva del turno pendiente de confirmación
    """,
    'author': 'Innatum',
    'website': 'https://www.innatum.com',
    'category': 'Services',
    'version': '18.0.1.5.0',
    'depends': [
        'innatum_agenda_core',
        'website',
    ],
    'data': [
        'views/appointment_templates.xml',
        'views/homepage_templates.xml',
        'views/website_menu_data.xml',
        'data/website_data.xml',
    ],
    'assets': {
        'web.assets_frontend': [
            'innatum_agenda_web/static/src/scss/homepage.scss',
            'innatum_agenda_web/static/src/scss/appointment_form.scss',
            'innatum_agenda_web/static/src/js/appointment_form.js',
            'innatum_agenda_web/static/src/js/hero_slideshow.js',
        ],
    },
    'demo': [],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
