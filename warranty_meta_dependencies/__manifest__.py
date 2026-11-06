# -*- coding: utf-8 -*-
{
    "name": "Warranty: Meta Dependencies",
    "summary": "Install this module to install every custom Warranty Module addon in one step.",
    "description": """
                   This meta module exists only to bundle and install the custom addons of the
                   Warranty Module project. Installing it installs every module listed in depends.
                   """,
    "version": "18.0.1.0.0",
    "category": "Sales/After-Sales",
    "license": "LGPL-3",
    "author": "Centrics Business Solutions (Pvt) Ltd",
    "website": "http://www.centrics.cloud/",
    "depends": [
        "amc_management",
        "amc_management_service",
        "amc_management_warranty",
        "material_purchase_requisitions",
        "warranty_management",
        "warranty_management_accounting",
        "warranty_management_fsm",
        "warranty_management_helpdesk",
        "warranty_management_mrf",
        "warranty_management_mrp",
        "warranty_management_repair",
    ],
    "data": [],
    "installable": True,
    "application": False,
    "auto_install": False,
}
