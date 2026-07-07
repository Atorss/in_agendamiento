# -*- coding: utf-8 -*-
{
    'name': 'Innatum Agenda - Planes y Suscripciones',
    'summary': 'Gestión de tenants SaaS: planes, suscripciones, recargas IA y wizard de provisioning',
    'description': """
        Innatum Agenda Planes — Capa SaaS del producto.

        Catálogo de planes (Básico, Pro, Enterprise) que Innatum vende a sus
        clientes. Cada tenant queda como una res.company con su suscripción
        asociada (1:1). El wizard de provisioning crea atómicamente la
        company, el website (con subdominio), el admin user del tenant y la
        suscripción inicial — garantizando que todos los partners
        estructurales nazcan con company_id correcto.

        Modelo de cobranza IA: el cliente compra "recargas" — un cobro fijo
        del cual Innatum retiene un % de utilidad. El resto se convierte en
        tokens consumibles. El consumo se imputa FIFO sobre las recargas
        ordenadas por fecha.

        Visible solo para grupo innatum_admin (Innatum staff). Los admins
        de tenant NO ven planes ni saldos brutos.
    """,
    'author': 'Innatum',
    'website': 'https://www.innatum.com',
    'category': 'Services',
    'version': '18.0.3.6.0',
    'depends': [
        'innatum_agenda_core',
        'website',
    ],
    'data': [
        'security/groups.xml',
        'security/ir.model.access.csv',
        'security/rules.xml',
        'data/planes_default.xml',
        'data/addons_default.xml',
        'data/sequences.xml',
        'data/cron.xml',
        'views/in_agenda_plan_views.xml',
        'views/in_agenda_addon_views.xml',
        'views/in_agenda_suscripcion_views.xml',
        'views/in_agenda_recarga_ia_views.xml',
        'wizard/wizard_tenant_provisioning_views.xml',
        'views/menus.xml',
        'views/in_agenda_servicio_catalogo_views.xml',
    ],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
