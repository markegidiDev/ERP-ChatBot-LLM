{
    'name': 'AI LiveBot - Warehouse Assistant',
    'version': '1.0',
    'category': 'Productivity',
    'summary': 'AI-powered chatbot for warehouse order management',
    'description': """
        Extends Odoo Live Chat with AI capabilities to:
        - Process warehouse orders via chat
        - Check stock availability
        - Create/validate delivery orders
        - Answer inventory questions
    """,
        'author': 'Marco Egidi',
    'website': 'https://yourwebsite.com',
    'depends': [
        'base',
        'mail',
        'stock',
        'sale_management',
    ],
    'data': [
        'security/ir.model.access.csv',
        'views/ai_config_views.xml',
    ],
    'assets': {
        'web.assets_backend': [
            'ai_livebot/static/src/xml/composer_dictation.xml',
            'ai_livebot/static/src/js/composer_dictation.js',
        ],
    },
    'icon': '/ai_livebot/static/description/icon.png',
    'installable': True,
    'application': True,
    'auto_install': False,
    'license': 'LGPL-3',
}
