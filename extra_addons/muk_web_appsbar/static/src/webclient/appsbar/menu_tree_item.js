import { Component, useState } from "@odoo/owl";

export class MenuTreeItem extends Component {
    static template = "muk_web_appsbar.MenuTreeItem";
    static components = { MenuTreeItem };
    static props = {
        group: Object,
        level: { type: Number, default: 1 },
        onSelectApp: Function,
        onExpandSidebar: Function,
        activeAppId: { type: Number, optional: true },
        sidebarCollapsed: Boolean,
    };

    setup() {
        this.state = useState({
            isExpanded: false
        });
    }

    get hasChildren() {
        return (this.props.group.children && this.props.group.children.length > 0) ||
               (this.props.group.apps && this.props.group.apps.length > 0);
    }

    get hasApps() {
        return this.props.group.apps && this.props.group.apps.length > 0;
    }

    get hasChildGroups() {
        return this.props.group.children && this.props.group.children.length > 0;
    }

    toggleExpand() {
        // If sidebar is collapsed, expand it first
        if (this.props.sidebarCollapsed) {
            this.props.onExpandSidebar();
            // After expanding, also expand this group
            if (this.hasChildren) {
                this.state.isExpanded = true;
            }
        } else if (this.hasChildren) {
            this.state.isExpanded = !this.state.isExpanded;
        }
    }

    getGroupClass() {
        const classes = [];

        if (this.props.level === 1) {
            classes.push('first_level');
        } else if (this.props.level === 2) {
            classes.push('second_level');
        }

        return classes.join(' ');
    }

    getCaretClass() {
        const classes = ['fa'];

        if (this.props.level === 1) {
            if (this.state.isExpanded) {
                classes.push('fa-chevron-down', 'fa--close');
            } else {
                classes.push('fa-chevron-right', 'fa--open');
            }
        } else {
            if (this.state.isExpanded) {
                classes.push('fa-chevron-down', 'fa--close_sub');
            } else {
                classes.push('fa-chevron-right', 'fa--open_sub');
            }
        }

        return classes.join(' ');
    }

    getSubmenuClass() {
        const classes = [];

        if (this.props.level === 1) {
            classes.push('sidebar_menu', 'menu_dropdown');
        } else if (this.props.level === 2) {
            classes.push('menu_dropdown_sub');
        }

        if (this.props.sidebarCollapsed) {
            classes.push('active_left');
        }

        return classes.join(' ');
    }

    isAppActive(app) {
        return this.props.activeAppId === app.id;
    }

    onAppClick(app) {
        this.props.onSelectApp(app);
    }
}
