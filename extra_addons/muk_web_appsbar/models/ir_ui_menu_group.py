from odoo import models, fields, api
import base64


class MenuGroup(models.Model):
    _name = 'ir.ui.menu.group'
    _description = 'Menu Group for Sidebar Navigation'
    _order = 'sequence, name'
    _parent_store = True

    name = fields.Char(
        string='Group Name',
        required=True,
        translate=True
    )

    sequence = fields.Integer(
        string='Sequence',
        default=10,
        help='Order of appearance in the sidebar'
    )

    parent_id = fields.Many2one(
        'ir.ui.menu.group',
        string='Parent Group',
        ondelete='cascade',
        index=True
    )

    parent_path = fields.Char(index=True, unaccent=False)

    child_ids = fields.One2many(
        'ir.ui.menu.group',
        'parent_id',
        string='Child Groups'
    )

    menu_ids = fields.Many2many(
        'ir.ui.menu',
        'menu_group_menu_rel',
        'group_id',
        'menu_id',
        string='Menus',
        domain=[('parent_id', '=', False)],
        help='Apps to include in this group'
    )

    icon = fields.Binary(
        string='Icon',
        attachment=True
    )

    icon_data = fields.Char(
        string='Icon Base64',
        compute='_compute_icon_data',
        store=False
    )

    active = fields.Boolean(
        default=True
    )

    level = fields.Integer(
        string='Level',
        compute='_compute_level',
        store=True
    )

    @api.depends('parent_id', 'parent_id.level')
    def _compute_level(self):
        for group in self:
            if not group.parent_id:
                group.level = 1
            else:
                group.level = group.parent_id.level + 1

    @api.depends('icon')
    def _compute_icon_data(self):
        for group in self:
            if group.icon:
                group.icon_data = group.icon.decode('utf-8') if isinstance(group.icon, bytes) else group.icon
            else:
                group.icon_data = False

    def get_menu_structure(self):
        """
        Returns the complete menu structure for the sidebar
        Optimized with single query
        """
        # Get all active groups
        all_groups = self.search([('active', '=', True)], order='sequence, name')

        # Build groups dict for faster lookup
        groups_dict = {}
        for group in all_groups:
            icon_base64 = False
            if group.icon:
                # El icono ya está almacenado como base64 en Odoo
                # Solo necesitamos asegurarnos de que sea una cadena
                if isinstance(group.icon, bytes):
                    icon_base64 = group.icon.decode('utf-8')
                else:
                    icon_base64 = group.icon

            groups_dict[group.id] = {
                'id': group.id,
                'name': group.name,
                'sequence': group.sequence,
                'parent_id': group.parent_id.id if group.parent_id else False,
                'icon': icon_base64,
                'level': group.level,
                'menu_ids': group.menu_ids.ids,
                'children': []
            }

        # Build tree structure
        root_groups = []
        for group_data in groups_dict.values():
            if group_data['parent_id']:
                parent = groups_dict.get(group_data['parent_id'])
                if parent:
                    parent['children'].append(group_data)
            else:
                root_groups.append(group_data)

        return root_groups
