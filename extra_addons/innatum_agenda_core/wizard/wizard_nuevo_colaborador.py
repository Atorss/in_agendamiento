# -*- coding: utf-8 -*-
"""Wizard para que el admin del tenant cree colaboradores (profesionales).

Patrón SaaS: el admin NO tiene permisos directos sobre hr.employee
(solo read-only para listarlos). Toda creación va por este wizard que
corre con sudo y respeta los límites del plan (max_profesionales).
"""

import logging

from odoo import models, fields, api, _
from odoo.exceptions import ValidationError

_logger = logging.getLogger(__name__)


class InAgendaColaboradorWizard(models.TransientModel):
    _name = 'in_agenda.colaborador.wizard'
    _description = 'Wizard: Nuevo Colaborador'

    name = fields.Char(string='Nombre completo', required=True)
    work_email = fields.Char(
        string='Correo de trabajo', required=True,
        help='Se usará como login del usuario.',
    )
    password = fields.Char(
        string='Contraseña inicial', required=True,
        help='Mínimo 8 caracteres. El colaborador debería cambiarla al '
             'primer login.',
    )
    identification_id = fields.Char(string='Cédula / Identificación')
    work_phone = fields.Char(string='Teléfono de trabajo')
    job_title = fields.Char(string='Cargo / Puesto')
    servicio_ids = fields.Many2many(
        'innatum.agenda.servicio',
        string='Servicios que atiende',
        help='Servicios para los cuales este colaborador puede ser '
             'asignado en planificaciones de horarios.',
        domain="[('company_id', 'in', allowed_company_ids)]",
    )

    @api.constrains('password')
    def _check_password(self):
        for rec in self:
            if rec.password and len(rec.password) < 8:
                raise ValidationError(_(
                    'La contraseña debe tener al menos 8 caracteres.'
                ))

    @api.constrains('work_email')
    def _check_email_format(self):
        for rec in self:
            if rec.work_email and '@' not in rec.work_email:
                raise ValidationError(_(
                    'Ingresa un email válido.'
                ))

    def action_crear(self):
        """Crea user + hr.employee con sudo, asigna grupo Usuario de Agenda.

        Valida que no exceda el límite max_profesionales del plan (la
        constraint en hr.employee también lo valida, pero acá lo
        adelantamos para una UX clara con mensaje del wizard).
        """
        self.ensure_one()
        company = self.env.company

        # Validar email único en el sistema
        if self.env['res.users'].sudo().search_count([('login', '=', self.work_email)]):
            raise ValidationError(_(
                'Ya existe un usuario con el email "%(email)s". Usa otro.',
                email=self.work_email,
            ))

        # Validar límite del plan ANTES de crear (defensa en profundidad —
        # la constraint en hr.employee también lo valida).
        Sus = self.env['in_agenda.suscripcion'].sudo()
        susc = Sus._ensure_active_for_company(company) if hasattr(Sus, '_ensure_active_for_company') else False
        if susc and susc.plan_id.max_profesionales:
            actuales = self.env['hr.employee'].sudo().search_count([
                ('company_id', '=', company.id),
                ('active', '=', True),
            ])
            if actuales + 1 > susc.plan_id.max_profesionales:
                raise ValidationError(_(
                    'El plan "%(plan)s" permite máximo %(limite)d '
                    'colaborador(es). Ya tienes %(actual)d.\n\n'
                    'Para aumentar este límite, contacta a Innatum.',
                    plan=susc.plan_id.name,
                    limite=susc.plan_id.max_profesionales,
                    actual=actuales,
                ))

        # 1. Crear usuario
        tz = self.env.user.tz or company.partner_id.tz or 'UTC'
        groups_colaborador = [
            self.env.ref('base.group_user').id,
            self.env.ref('innatum_agenda_core.innatum_agenda_group_user').id,
        ]
        user = self.env['res.users'].sudo().with_context(
            no_reset_password=True,
        ).create({
            'name': self.name,
            'login': self.work_email,
            'email': self.work_email,
            'password': self.password,
            'company_id': company.id,
            'company_ids': [(6, 0, [company.id])],
            'groups_id': [(6, 0, groups_colaborador)],
            'tz': tz,
        })
        # Aislar el partner del user al tenant (igual que el wizard de tenant)
        user.partner_id.sudo().write({
            'company_id': company.id,
            'tz': tz,
        })

        # 2. Crear hr.employee linkeado al user, con los servicios que atiende.
        #    Fijamos explícitamente el horario de trabajo (resource_calendar_id)
        #    al calendario de LA EMPRESA del tenant. Sin esto, hr.employee lo
        #    resuelve desde self.env.company (la empresa activa del que crea),
        #    que en el provisioning es Innatum → el empleado quedaría con el
        #    calendario de otra empresa (fuga multi-tenant y disponibilidad
        #    directa incorrecta). El admin puede cambiarlo luego por uno propio.
        emp_vals = {
            'name': self.name,
            'work_email': self.work_email,
            'work_phone': self.work_phone or False,
            'job_title': self.job_title or False,
            'identification_id': self.identification_id or False,
            'user_id': user.id,
            'company_id': company.id,
            'servicio_ids': [(6, 0, self.servicio_ids.ids)],
        }
        if company.resource_calendar_id:
            emp_vals['resource_calendar_id'] = company.resource_calendar_id.id
        employee = self.env['hr.employee'].sudo().create(emp_vals)

        _logger.info(
            'Colaborador creado en tenant company=%s: user=%s emp=%s servicios=%s',
            company.name, user.id, employee.id, self.servicio_ids.ids,
        )

        # 4. Abrir el form del empleado recién creado
        return {
            'type': 'ir.actions.act_window',
            'name': _('Colaborador creado'),
            'res_model': 'hr.employee',
            'res_id': employee.id,
            'view_mode': 'form',
            'target': 'current',
        }


class InAgendaColaboradorAccesoWizard(models.TransientModel):
    """Wizard para que el admin del tenant cambie el correo de trabajo y/o la
    contraseña de un colaborador. Corre con sudo y SINCRONIZA el cambio en:
    el empleado (work_email + work_contact), su usuario (login/email/password)
    y el partner del usuario."""
    _name = 'in_agenda.colaborador.acceso.wizard'
    _description = 'Wizard: Cambiar acceso de colaborador'

    employee_id = fields.Many2one(
        'hr.employee', string='Colaborador', required=True, readonly=True)
    user_id = fields.Many2one(
        'res.users', related='employee_id.user_id', readonly=True)
    new_work_email = fields.Char(string='Correo de trabajo', required=True)
    new_password = fields.Char(
        string='Nueva contraseña',
        help='Déjala vacía para NO cambiarla. Mínimo 8 caracteres.')

    @api.onchange('employee_id')
    def _onchange_employee_id(self):
        if self.employee_id:
            self.new_work_email = self.employee_id.work_email

    @api.constrains('new_work_email')
    def _check_email_format(self):
        for rec in self:
            if rec.new_work_email and '@' not in rec.new_work_email:
                raise ValidationError(_('Ingresa un email válido.'))

    @api.constrains('new_password')
    def _check_password(self):
        for rec in self:
            if rec.new_password and len(rec.new_password) < 8:
                raise ValidationError(_(
                    'La contraseña debe tener al menos 8 caracteres.'))

    def action_aplicar(self):
        self.ensure_one()
        emp = self.employee_id.sudo()
        email = (self.new_work_email or '').strip()
        user = emp.user_id.sudo()

        # Login único en el sistema (excluyendo al propio usuario)
        if email:
            dup = self.env['res.users'].sudo().search([
                ('login', '=', email),
                ('id', '!=', user.id if user else 0),
            ], limit=1)
            if dup:
                raise ValidationError(_(
                    'Ya existe un usuario con el correo "%s". Usa otro.') % email)

        # 1. Empleado
        if email:
            emp.write({'work_email': email})
            if emp.work_contact_id:
                emp.work_contact_id.sudo().write({'email': email})

        # 2. Usuario (login/email/password) + su partner
        if user:
            uvals = {}
            if email:
                uvals['login'] = email
                uvals['email'] = email
            if self.new_password:
                uvals['password'] = self.new_password
            if uvals:
                user.with_context(no_reset_password=True).write(uvals)
            if email and user.partner_id:
                user.partner_id.sudo().write({'email': email})

        _logger.info(
            'Acceso de colaborador actualizado emp=%s user=%s (email=%s, pass=%s)',
            emp.id, user.id if user else None, bool(email), bool(self.new_password))
        return {'type': 'ir.actions.act_window_close'}


class InAgendaColaboradorServiciosWizard(models.TransientModel):
    """Wizard para editar (agregar/quitar) los servicios que atiende un
    colaborador. El admin del tenant tiene hr.employee read-only, así que el
    cambio se aplica con sudo desde aquí."""
    _name = 'in_agenda.colaborador.servicios.wizard'
    _description = 'Wizard: Editar servicios del colaborador'

    employee_id = fields.Many2one(
        'hr.employee', string='Colaborador', required=True, readonly=True)
    servicio_ids = fields.Many2many(
        'innatum.agenda.servicio',
        'in_agenda_colab_serv_wiz_rel', 'wizard_id', 'servicio_id',
        string='Servicios que atiende',
        domain="[('company_id', 'in', allowed_company_ids)]",
        help='Servicios del catálogo habilitados para tu negocio que este '
             'colaborador brinda.')

    @api.onchange('employee_id')
    def _onchange_employee_id(self):
        if self.employee_id:
            self.servicio_ids = self.employee_id.servicio_ids

    def action_aplicar(self):
        self.ensure_one()
        self.employee_id.sudo().write({
            'servicio_ids': [(6, 0, self.servicio_ids.ids)]})
        _logger.info(
            'Servicios de colaborador emp=%s actualizados: %s',
            self.employee_id.id, self.servicio_ids.ids)
        return {'type': 'ir.actions.act_window_close'}


class InAgendaColaboradorHorarioWizard(models.TransientModel):
    """Wizard para asignar/cambiar el horario de trabajo (resource.calendar)
    de un colaborador. Relevante en modo de agenda 'directa', donde la
    disponibilidad se calcula a partir de ese horario. El admin tiene el form
    del colaborador en solo lectura, así que el cambio se aplica con sudo."""
    _name = 'in_agenda.colaborador.horario.wizard'
    _description = 'Wizard: Cambiar horario de trabajo del colaborador'

    employee_id = fields.Many2one(
        'hr.employee', string='Colaborador', required=True, readonly=True)
    resource_calendar_id = fields.Many2one(
        'resource.calendar', string='Horario de trabajo',
        domain="[('company_id', 'in', allowed_company_ids)]",
        help='Horario semanal de atención del colaborador. Podés reutilizar '
             'uno existente o crear uno nuevo (se gestionan en el menú '
             'Configuración → Horarios de trabajo).')

    @api.onchange('employee_id')
    def _onchange_employee_id(self):
        if self.employee_id:
            self.resource_calendar_id = self.employee_id.resource_calendar_id

    def action_aplicar(self):
        self.ensure_one()
        if not self.resource_calendar_id:
            raise ValidationError(_('Selecciona un horario de trabajo.'))
        self.employee_id.sudo().write({
            'resource_calendar_id': self.resource_calendar_id.id})
        _logger.info(
            'Horario de colaborador emp=%s actualizado: calendar=%s',
            self.employee_id.id, self.resource_calendar_id.id)
        return {'type': 'ir.actions.act_window_close'}
