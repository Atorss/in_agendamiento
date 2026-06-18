{
    'name': 'Innatum - MuK Groups (Agenda)', 
    'summary': 'Adds expand/collapse for views',
    'description': '''
        Enables you to expand and collapse groups that were created by 
        grouping the data by a certain field for list and kanban views.
    ''',
    'version': '18.0.1.0.0',
    'category': 'Tools/UI',
    'license': 'LGPL-3', 
    'author': 'Innatum',
    'website': 'https://www.innatum.com',
    'live_test_url': 'https://youtu.be/XiMde7ROg-kS',
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
            '/muk_web_group/static/src/**/*',
        ],
        'web.assets_unit_tests': [
            'muk_web_group/static/tests/**/*',
        ],
    },
    'images': [
        'static/description/banner.png',
    ],
    'installable': True,
    'application': False,
    'auto_install': False,
}
