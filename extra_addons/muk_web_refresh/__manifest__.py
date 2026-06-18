{
    'name': 'Innatum - MuK Web Refresh (Agenda)', 
    'summary': 'Automatically refresh any list or kanban view',
    'description': '''
        Activate the auto refresh button to reload the view every
        30 seconds. The refresh will reload and update the data
        of the view.
    ''',
    'version': '18.0.1.0.0',
    'category': 'Tools/UI',
    'license': 'LGPL-3', 
    'author': 'Innatum',
    'website': 'https://www.innatum.com',
    'live_test_url': 'https://youtu.be/LmDAgBBWZBQ',
    'contributors': [
        'Innatum Development Team',
        'MuK IT (modulo base original)',
        'Mathias Markl <mathias.markl@mukit.at> (autor original MuK)',
    ],
    'depends': [
        'web',
    ],
    'assets': {
        'web.assets_backend': [            
            (
                'after',
                '/web/static/src/search/control_panel/control_panel.js',
                '/muk_web_refresh/static/src/search/control_panel.js',
            ),            
            (
                'after',
                '/web/static/src/search/control_panel/control_panel.xml',
                '/muk_web_refresh/static/src/search/control_panel.xml',
            ),
        ],
        'web.assets_unit_tests': [
            'muk_web_refresh/static/tests/**/*',
        ],
    },
    'images': [
        'static/description/banner.png',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
