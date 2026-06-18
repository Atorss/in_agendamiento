{
    'name': 'Innatum - MuK Chatter (Agenda)', 
    'summary': 'Adds options for the chatter',
    'description': '''
        This module improves the design of the chatter and adds a user
        preference to set the position of the chatter in the form view.
    ''',
    'version': '18.0.1.2.3',
    'category': 'Tools/UI',
    'license': 'LGPL-3', 
    'author': 'Innatum',
    'website': 'https://www.innatum.com',
    'live_test_url': 'https://my.mukit.at/r/f6m',
    'contributors': [
        'Innatum Development Team',
        'MuK IT (modulo base original)',
        'Mathias Markl <mathias.markl@mukit.at> (autor original MuK)',
    ],
    'depends': [
        'mail',
    ],
    'data': [
        'views/res_users.xml',
    ],
    'assets': {
        'web._assets_primary_variables': [
            (
                'after', 
                'web/static/src/scss/primary_variables.scss', 
                'muk_web_chatter/static/src/scss/variables.scss'
            ),
        ],
        'web.assets_backend': [
            'muk_web_chatter/static/src/core/**/*.*',
            'muk_web_chatter/static/src/chatter/*.scss',
            'muk_web_chatter/static/src/chatter/*.xml',
            (
                'after', 
                'mail/static/src/chatter/web_portal/chatter.js', 
                'muk_web_chatter/static/src/chatter/chatter.js'
            ),
            (
                'after', 
                'mail/static/src/chatter/web/form_compiler.js', 
                'muk_web_chatter/static/src/views/form/form_compiler.js'
            ),
            'muk_web_chatter/static/src/views/form/form_renderer.js',
        ],
    },
    'images': [
        'static/description/banner.png',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
