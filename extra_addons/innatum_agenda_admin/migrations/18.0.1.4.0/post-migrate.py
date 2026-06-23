# -*- coding: utf-8 -*-
"""Wira "Colaboradores" al grupo MUK "Administración".

Necesario para instalaciones EXISTENTES: el record del grupo
(`muk_web_appsbar.menu_group_medic_administracion`) es noupdate=1, por lo que
un `-u` NO re-aplica el wiring declarativo de data/menu_groups_wiring.xml.
Esta migración lo hace imperativamente (idempotente).
"""
from odoo import api, SUPERUSER_ID


def migrate(cr, version):
    env = api.Environment(cr, SUPERUSER_ID, {})
    group = env.ref('muk_web_appsbar.menu_group_medic_administracion',
                    raise_if_not_found=False)
    if not group:
        return
    menu = env.ref('innatum_agenda_core.menu_innatum_colaboradores_root',
                   raise_if_not_found=False)
    if menu:
        group.write({'menu_ids': [(4, menu.id)]})
