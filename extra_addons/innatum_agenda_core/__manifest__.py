# -*- coding: utf-8 -*-
{
    'name': 'Innatum Agenda Core',
    'summary': 'Sistema genérico de agendamiento de citas y planificación de horarios',
    'description': """
        Innatum Agenda Core — Módulo genérico de agendamiento.
        Gestión de servicios, turnos, planificación de horarios
        y generación algorítmica de slots.
        Puede ser usado por cualquier tipo de negocio:
        consultorios, peluquerías, lavaderos de autos, etc.
    """,
    'author': 'Innatum',
    'website': 'https://www.innatum.com',
    'category': 'Services',
    'version': '18.0.4.47.0',
    'depends': [
        'base',
        'mail',
        'contacts',
        'hr',
        'l10n_latam_base',
    ],
    'data': [
        'security/innatum_agenda_security.xml',
        'security/ir.model.access.csv',
        'security/innatum_agenda_rules.xml',
        'wizard/wizard_nuevo_colaborador_views.xml',
        'views/innatum_agenda_config_views.xml',
        'views/innatum_agenda_turno_views.xml',
        'views/innatum_agenda_servicio_views.xml',
        'views/innatum_agenda_menus.xml',
        'views/innatum_agenda_bloqueo_views.xml',
        'views/innatum_agenda_derivacion_views.xml',
        'views/innatum_agenda_calendario_views.xml',
        'views/res_partner_clientes_views.xml',
        'views/hr_employee_colaborador_views.xml',
        'views/res_company_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'innatum_agenda_core/static/src/js/calendar_business_hours.js',
            'innatum_agenda_core/static/src/scss/calendar_business_hours.scss',
        ],
    },
    'demo': [],
    'installable': True,
    'application': True,
    'license': 'LGPL-3',
}
