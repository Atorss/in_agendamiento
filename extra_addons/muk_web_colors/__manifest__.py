{
    'name': 'Innatum - MuK Colors (Agenda)',
    'summary': 'Personalizacion de colores teal/celeste para Innatum Agenda (basado en MuK Colors)',
    'description': '''
        Personalizacion de Innatum sobre el modulo MuK Colors original.
        Aplica la paleta teal pastel (celeste) basada en el sitio publico
        de Innatum Agenda a las variables primarias del backend de Odoo.
    ''',
    'version': '18.0.1.0.8',
    'category': 'Tools/UI',
    'license': 'LGPL-3',
    'author': 'Innatum',
    'website': 'https://www.innatum.com',
    'contributors': [
        'Innatum Development Team',
        'MuK IT (modulo base original)',
        'Mathias Markl <mathias.markl@mukit.at> (autor original MuK)',
    ],
    'depends': [
        'base_setup',
        'web_editor',
    ],
    'data': [
        'templates/webclient.xml',
        'views/res_config_settings.xml',
    ],
    'assets': {
        'web._assets_primary_variables': [
            ('prepend', 'muk_web_colors/static/src/scss/colors.scss'),
            (
                'before',
                'muk_web_colors/static/src/scss/colors.scss',
                'muk_web_colors/static/src/scss/colors_light.scss'
            ),
            # Overrides Innatum Agenda: paleta teal celeste
            (
                'after',
                'muk_web_colors/static/src/scss/colors_light.scss',
                'muk_web_colors/static/src/scss/agenda_overrides.scss'
            ),
        ],
        'web.assets_web_dark': [
            (
                'after',
                'muk_web_colors/static/src/scss/colors.scss',
                'muk_web_colors/static/src/scss/colors_dark.scss'
            ),
        ],
    },
    'images': [
        'static/description/banner.png',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
    'uninstall_hook': '_uninstall_cleanup',
}