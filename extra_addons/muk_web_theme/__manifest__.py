{
    'name': 'Innatum - MuK Backend Theme (Agenda)',
    'summary': 'Tema backend Innatum Agenda teal/celeste (basado en MuK Backend Theme)',
    'description': '''
        Personalizacion de Innatum sobre el modulo MuK Backend Theme original.
        Aplica estilos custom de Innatum Agenda (paleta teal celeste,
        componentes, navbar, formularios) sobre la base de MuK.
    ''',
    'version': '18.0.1.2.7',
    'category': 'Themes/Backend',
    'license': 'LGPL-3',
    'author': 'Innatum',
    'website': 'https://www.innatum.com',
    'contributors': [
        'Innatum Development Team',
        'MuK IT (modulo base original)',
        'Mathias Markl <mathias.markl@mukit.at> (autor original MuK)',
    ],
    'depends': [
        'muk_web_chatter',
        'muk_web_dialog',
        'muk_web_appsbar',
        'muk_web_colors',
    ],
    'excludes': [
        'web_enterprise',
    ],
    'data': [
        'templates/web_layout.xml',
        'views/res_config_settings.xml',
    ],
    'assets': {
        'web._assets_primary_variables': [
            (
                'after',
                'web/static/src/scss/primary_variables.scss',
                'muk_web_theme/static/src/scss/colors.scss'
            ),
            (
                'after',
                'web/static/src/scss/primary_variables.scss',
                'muk_web_theme/static/src/scss/variables.scss'
            ),
        ],
        'web.assets_backend': [
            'muk_web_theme/static/src/webclient/**/*.xml',
            'muk_web_theme/static/src/webclient/**/*.scss',
            'muk_web_theme/static/src/webclient/**/*.js',
            'muk_web_theme/static/src/views/**/*.scss',
            # Personalizacion Innatum Agenda
            'muk_web_theme/static/src/scss/agenda_backend.scss',
        ],
    },
    'images': [
        'static/description/banner.png',
        'static/description/theme_screenshot.png'
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
    'post_init_hook': '_setup_module',
    'uninstall_hook': '_uninstall_cleanup',
}