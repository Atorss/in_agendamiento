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
        domain="[('company_ids', 'in', allowed_company_ids)]",
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

        # 2. Crear hr.employee linkeado al user
        employee = self.env['hr.employee'].sudo().create({
            'name': self.name,
            'work_email': self.work_email,
            'work_phone': self.work_phone or False,
            'job_title': self.job_title or False,
            'identification_id': self.identification_id or False,
            'user_id': user.id,
            'company_id': company.id,
        })

        _logger.info(
            'Colaborador creado en tenant company=%s: user=%s emp=%s',
            company.name, user.id, employee.id,
        )

        # 3. Si seleccionó servicios, los anotamos como notas internas
        # (los servicios se vinculan al profesional vía planificación,
        # no directamente en hr.employee — esto solo queda como referencia
        # para que el admin recuerde qué crear en la planificación)
        if self.servicio_ids:
            nombres = ', '.join(self.servicio_ids.mapped('name'))
            employee.sudo().message_post(
                body=_('Servicios sugeridos para asignar en planificación: '
                       '%s') % nombres,
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
