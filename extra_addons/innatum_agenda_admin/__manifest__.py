# -*- coding: utf-8 -*-
{
    'name': 'Innatum Agenda Admin',
    'summary': 'Administración del tenant: gestión simplificada de personal y configuración',
    'description': """
        Innatum Agenda Admin — Capa administrativa del SaaS.
        - Menú "Administración → Personal" con vista simplificada para crear empleados
          asociados a servicios.
        - El Administrador de Agenda hereda permisos de Oficial RRHH para poder
          dar de alta personal de su empresa.
        - La vista estándar de Empleados queda en modo lectura para evitar
          alteraciones por canales no controlados.
    """,
    'author': 'Innatum',
    'website': 'https://www.innatum.com',
    'category': 'Services',
    'version': '18.0.1.5.0',
    'depends': [
        'innatum_agenda_core',
        'hr',
        'contacts',
        'spreadsheet_dashboard',
        'muk_web_appsbar',
    ],
    'data': [
        'security/innatum_agenda_admin_groups.xml',
        'security/ir.model.access.csv',
        'wizard/wizard_set_password_views.xml',
        'views/hr_employee_views.xml',
        'views/hr_employee_colaborador_planif_inherit.xml',
        'views/hr_employee_public_views.xml',
        'views/res_company_views.xml',
        'views/menus.xml',
        'data/menu_groups_wiring.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
