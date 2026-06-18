import { url } from '@web/core/utils/urls';
import { useService } from '@web/core/utils/hooks';

import { Component, onWillUnmount, useState } from '@odoo/owl';
import { MenuTreeItem } from './menu_tree_item';

export class AppsBar extends Component {
    static template = 'muk_web_appsbar.AppsBar';
    static props = {};
    static components = { MenuTreeItem };

    setup() {
        this.companyService = useService('company');
        this.appMenuService = useService('app_menu');

        this.state = useState({
            menuGroups: [],
            ungroupedApps: [],
            isCollapsed: false,
            isLoading: true
        });

        if (this.companyService.currentCompany.has_appsbar_image) {
            this.sidebarImageUrl = url('/web/image', {
                model: 'res.company',
                field: 'appbar_image',
                id: this.companyService.currentCompany.id,
            });
        }

        this._loadMenuGroups();

        const renderAfterMenuChange = () => {
            this._loadMenuGroups();
        };
        this.env.bus.addEventListener(
            'MENUS:APP-CHANGED', renderAfterMenuChange
        );
        onWillUnmount(() => {
            this.env.bus.removeEventListener(
                'MENUS:APP-CHANGED', renderAfterMenuChange
            );
        });
    }

    async _loadMenuGroups() {
        this.state.isLoading = true;
        try {
            this.state.menuGroups = await this.appMenuService.getMenuGroups();
            this.state.ungroupedApps = await this.appMenuService.getUngroupedApps();
        } catch (error) {
            console.error('Error loading menu groups:', error);
            this.state.menuGroups = [];
            this.state.ungroupedApps = this.appMenuService.getAppsMenuItems();
        }
        this.state.isLoading = false;
    }

    get currentApp() {
        return this.appMenuService.getCurrentApp();
    }

    get activeAppId() {
        return this.currentApp?.id;
    }

    toggleSidebar() {
        this.state.isCollapsed = !this.state.isCollapsed;
        const sidebar = document.getElementById('sidebar_panel');
        const webClient = document.querySelector('.o_web_client');
        if (sidebar && webClient) {
            if (this.state.isCollapsed) {
                sidebar.classList.add('mk_collapsed');
                webClient.classList.add('mk_sidebar_collapsed');
            } else {
                sidebar.classList.remove('mk_collapsed');
                webClient.classList.remove('mk_sidebar_collapsed');
            }
        }
    }

    _onAppClick(app) {
        if (this.state.isCollapsed) {
            this._expandSidebar();
        }
        return this.appMenuService.selectApp(app);
    }

    _expandSidebar() {
        if (this.state.isCollapsed) {
            this.state.isCollapsed = false;
            const sidebar = document.getElementById('sidebar_panel');
            const webClient = document.querySelector('.o_web_client');
            if (sidebar && webClient) {
                sidebar.classList.remove('mk_collapsed');
                webClient.classList.remove('mk_sidebar_collapsed');
            }
        }
    }
}
