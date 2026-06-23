# -*- coding: utf-8 -*-
{
    'name': 'Innatum Agenda - Vertical Odontologico (Web)',
    'summary': 'Homepage data-driven estilo clinica dental sobre Innatum Agenda',
    'description': """
        Vertical odontologico para Innatum Agenda Web.
        Provee un homepage estilo clinica dental (hero, especialidades, equipo,
        armonizacion facial, contacto) que se activa automaticamente cuando
        res.company.vertical == 'odonto'. Los datos visibles (nombre, telefono,
        equipo, servicios) salen del tenant actual (request.website.company_id),
        no estan hardcoded.

        Instalable opcional: solo se necesita en BDs que tengan al menos un
        tenant con vertical odontologico.
    """,
    'author': 'Innatum',
    'website': 'https://www.innatum.com',
    'category': 'Services',
    'version': '18.0.1.4.0',
    'depends': [
        'innatum_agenda_web',
    ],
    'data': [
        'views/homepage_templates.xml',
    ],
    'assets': {
        'web.assets_frontend': [
            'innatum_agenda_web_odonto/static/src/scss/homepage.scss',
            'innatum_agenda_web_odonto/static/src/scss/appointment_form.scss',
            'innatum_agenda_web_odonto/static/src/js/contact_form.js',
            'innatum_agenda_web_odonto/static/src/js/scroll_animations.js',
        ],
    },
    'demo': [],
    'installable': True,
    'application': False,
    'license': 'LGPL-3',
}
