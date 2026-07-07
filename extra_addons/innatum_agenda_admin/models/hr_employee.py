# -*- coding: utf-8 -*-

import logging

from odoo import models, fields, api
from odoo.exceptions import ValidationError, UserError

_logger = logging.getLogger(__name__)


ROL_GROUP_REF = {
    'usuario': 'innatum_agenda_core.innatum_agenda_group_user',
    'operador': 'innatum_agenda_core.innatum_agenda_group_operator',
    'admin': 'innatum_agenda_core.innatum_agenda_group_admin',
}


class HrEmployee(models.Model):
    _inherit = 'hr.employee'

    innatum_agenda_rol = fields.Selection([
        ('usuario', 'Usuario — Atiende clientes; ve solo su agenda'),
        ('operador', 'Operador — Gestiona la agenda y turnos del equipo'),
        ('admin', 'Administrador — Control total: empleados, empresa, facturación'),
    ], string='Rol en Agenda', default='usuario',
       help='Nivel de acceso del empleado al sistema de Agenda.\n\n'
            '• Usuario: solo ve y gestiona su propia agenda. '
            'Para crear planificaciones requiere el flag "Puede crear su planificación". '
            'Para facturar requiere el flag "Puede facturar".\n\n'
            '• Operador: gestiona turnos y planificaciones de todos los '
            'profesionales del equipo, edita el catálogo de servicios y factura. '
            'No puede crear empleados ni editar datos de la empresa.\n\n'
            '• Administrador: control total — además de lo del Operador, '
            'crea empleados desde "Administración → Personal", edita los datos '
            'fiscales y facturación electrónica de la empresa, y puede eliminar '
            'registros maestros.'
    )
    puede_planificar = fields.Boolean(
        string='Puede crear su planificación', default=True,
        help='Si está activo, este empleado puede crear y reprogramar su '
             'propia planificación de horarios aunque su rol sea solo '
             '"Usuario" (siempre limitado a SU agenda).\n\n'
             'Activo por defecto: cada profesional administra su agenda. '
             'El administrador puede desactivarlo para un colaborador puntual.\n\n'
             'Operador y Administrador siempre pueden crear planificaciones, '
             'sin importar este flag.',
    )

    def action_toggle_puede_planificar(self):
        """Permite al admin del tenant activar/desactivar el permiso de
        autoplanificación de un colaborador. Corre con sudo porque el admin
        tiene hr.employee en read-only; protegido al grupo Administrador."""
        if not self.env.user.has_group(
                'innatum_agenda_core.innatum_agenda_group_admin'):
            raise UserError(
                'Solo el Administrador del negocio puede cambiar este permiso.')
        for emp in self:
            emp.sudo().write({'puede_planificar': not emp.puede_planificar})
            _logger.info(
                'innatum_agenda_admin: puede_planificar de emp=%d -> %s (por %s)',
                emp.id, emp.puede_planificar, self.env.user.login)
        return True

    def _innatum_agenda_groups_for_rol(self, rol):
        """Devuelve un recordset res.groups con base.group_user + el grupo
        de Agenda correspondiente al rol indicado."""
        groups = self.env.ref('base.group_user')
        ref = ROL_GROUP_REF.get(rol or 'usuario', ROL_GROUP_REF['usuario'])
        agenda_group = self.env.ref(ref, raise_if_not_found=False)
        if agenda_group:
            groups |= agenda_group
        return groups

    def _innatum_agenda_sync_user_groups(self):
        """Sincroniza el rol del empleado con los grupos del res.users
        vinculado. Mantiene los grupos no relacionados a Agenda."""
        all_agenda_groups = self.env['res.groups']
        for ref in ROL_GROUP_REF.values():
            grp = self.env.ref(ref, raise_if_not_found=False)
            if grp:
                all_agenda_groups |= grp

        for emp in self.filtered(lambda e: e.user_id):
            target = emp._innatum_agenda_groups_for_rol(emp.innatum_agenda_rol)
            commands = [(3, g.id) for g in all_agenda_groups]
            commands += [(4, g.id) for g in target]
            emp.user_id.sudo().write({'groups_id': commands})

    def write(self, vals):
        """Sincroniza work_email con el login/email del res.users vinculado
        y los grupos del usuario con el rol seleccionado en el empleado.
        """
        new_email = vals.get('work_email')
        if new_email is not None:
            new_email = (new_email or '').strip().lower()
            for emp in self.filtered(lambda e: e.user_id):
                old_email = (emp.work_email or '').strip().lower()
                if new_email and new_email != old_email:
                    Users = self.env['res.users'].sudo()
                    if Users.search_count([
                        ('login', '=', new_email),
                        ('id', '!=', emp.user_id.id),
                    ]):
                        raise ValidationError(
                            f"Ya existe otro usuario con el correo '{new_email}'. "
                            f"No se puede actualizar el empleado."
                        )
                    emp.user_id.sudo().write({
                        'login': new_email,
                        'email': new_email,
                    })
                    _logger.info(
                        'innatum_agenda_admin: login del usuario id=%d actualizado a %s',
                        emp.user_id.id, new_email,
                    )

        result = super().write(vals)

        if 'innatum_agenda_rol' in vals:
            self._innatum_agenda_sync_user_groups()

        return result

    @api.model_create_multi
    def create(self, vals_list):
        """Si el empleado se crea desde el menú "Administración → Personal"
        (contexto innatum_auto_create_user=True) y no tiene user_id,
        crea automáticamente un res.users con work_email como login
        y lo vincula al empleado.
        """
        auto_create = self.env.context.get('innatum_auto_create_user')

        for vals in vals_list:
            if not auto_create or vals.get('user_id'):
                continue

            work_email = (vals.get('work_email') or '').strip().lower()
            if not work_email:
                raise ValidationError(
                    "Para registrar a un miembro del personal es obligatorio "
                    "proveer el correo de trabajo. Se usará para crear su usuario."
                )

            Users = self.env['res.users'].sudo()
            if Users.search_count([('login', '=', work_email)]):
                raise ValidationError(
                    f"Ya existe un usuario con el correo '{work_email}'. "
                    f"Usa otro correo o vincula al empleado existente."
                )

            rol = vals.get('innatum_agenda_rol') or 'usuario'
            target_groups = self._innatum_agenda_groups_for_rol(rol)

            user = Users.create({
                'name': vals.get('name'),
                'login': work_email,
                'email': work_email,
                'company_id': self.env.company.id,
                'company_ids': [(6, 0, [self.env.company.id])],
                'groups_id': [(6, 0, target_groups.ids)],
            })
            vals['user_id'] = user.id
            vals.setdefault('work_email', work_email)
            _logger.info(
                'innatum_agenda_admin: usuario "%s" (id=%d) creado para empleado "%s"',
                work_email, user.id, vals.get('name'),
            )

            # Email de "configura tu contraseña" — best effort
            try:
                user.action_reset_password()
            except Exception as exc:
                _logger.warning(
                    'innatum_agenda_admin: no se envió email de bienvenida a %s: %s',
                    work_email, exc,
                )

        return super().create(vals_list)

    def action_innatum_set_password(self):
        """Abre el wizard que permite al admin asignar manualmente la
        contraseña del usuario vinculado al empleado."""
        self.ensure_one()
        if not self.user_id:
            raise UserError(
                'Este empleado no tiene un usuario vinculado.'
            )
        return {
            'type': 'ir.actions.act_window',
            'name': 'Establecer Contraseña',
            'res_model': 'innatum.agenda.admin.wizard.set_password',
            'view_mode': 'form',
            'target': 'new',
            'context': {'default_employee_id': self.id},
        }


class HrEmployeePublic(models.Model):
    """Expone en el perfil PÚBLICO del empleado los campos de rol/permiso de
    Agenda.

    Motivo: hr.employee._check_private_fields considera "privado" (y lanza
    AccessError) cualquier campo que NO exista en hr.employee.public. Como
    'innatum_agenda_rol' y 'puede_planificar' son campos almacenados, cuando
    un usuario no-HR lee CUALQUIER campo de otro empleado (p.ej. avatar_128 o
    display_name vía prefetch), estos entran en el lote de lectura y disparan
    el error. Exponerlos aquí (igual que 'servicio_ids') los vuelve legibles
    y elimina el error en toda la app (turnos, derivaciones, kanban, etc.).
    Son de solo lectura y su valor real sigue viviendo en hr.employee.
    """
    _inherit = 'hr.employee.public'

    innatum_agenda_rol = fields.Selection(
        related='employee_id.innatum_agenda_rol', string='Rol en Agenda',
        readonly=True)
    puede_planificar = fields.Boolean(
        related='employee_id.puede_planificar',
        string='Puede crear su planificación', readonly=True)
