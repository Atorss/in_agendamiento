# -*- coding: utf-8 -*-
{
    'name': 'Innatum SaaS — Instalación Básica',
    'summary': 'Pack mínimo del SaaS de agendamiento: agenda, suscripciones y sitio web público',
    'description': """
        Módulo meta (sin código propio) que instala el stack mínimo del
        SaaS de agendamiento Innatum:

        - innatum_agenda_core: turnos, planificaciones, servicios,
          colaboradores, multi-tenant rules.
        - innatum_agenda_planes: planes, suscripciones, recargas IA,
          wizard de provisioning de tenants.
        - innatum_agenda_web: sitio público con formulario de reserva.

        NO incluye: chatbot IA (instalá innatum_ia para eso) ni
        facturación electrónica (instalá innatum_contable para Ecuador).

        Es la base que cualquier instancia productiva debe tener instalada
        antes de crear tenants vía el wizard.
    """,
    'author': 'Innatum',
    'website': 'https://www.innatum.com',
    'category': 'Services',
    'version': '18.0.1.1.0',
    'depends': [
        'innatum_agenda_core',
        'innatum_agenda_planes',
        'innatum_agenda_web',
    ],
    'data': [
        'data/admin_groups.xml',
    ],
    'installable': True,
    'application': True,
    'auto_install': False,
    'license': 'LGPL-3',
}
