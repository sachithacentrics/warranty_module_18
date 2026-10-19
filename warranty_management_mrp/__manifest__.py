{
    'name': 'Warranty Management - Kit Serials',
    'version': '18.0.1.0.0',
    'category': 'Sales/After-Sales',
    'summary': 'Indoor / Outdoor serial numbers of Kit products on the warranty units',
    'description': """
Bridge between Warranty Management and Sales / Manufacturing Kits (approved K1-K4):

* Warranty Component Role (Indoor Unit / Outdoor Unit / None) on Kit BoM lines
* Indoor / Outdoor serial numbers of the delivered kit components on each warranty unit,
  paired in delivery order, correctable while the card is Draft / Ready to Confirm
* Card Indoor / Outdoor Serial No. filled for single-unit cards
* Warranty confirmation requires the Indoor / Outdoor serials of kit units
""",
    'depends': ['warranty_management', 'sale_mrp'],
    'data': [
        'views/mrp_bom_views.xml',
        'views/warranty_card_views.xml',
        'views/warranty_unit_views.xml',
    ],
    'installable': True,
    'auto_install': True,
    'license': 'LGPL-3',
}
