import { registry } from "@web/core/registry";
import { user } from "@web/core/user";
import { rpc } from "@web/core/network/rpc";

import { computeAppsAndMenuItems, reorderApps } from "@web/webclient/menus/menu_helpers";

export const appMenuService = {
    dependencies: ["menu"],
    async start(env, { menu }) {
        let menuGroups = null;
        let menuGroupsTree = null;

        async function loadMenuGroups() {
            if (menuGroups !== null) {
                return menuGroups;
            }

            try {
                menuGroupsTree = await rpc('/web/dataset/call_kw/ir.ui.menu.group/get_menu_structure', {
                    model: 'ir.ui.menu.group',
                    method: 'get_menu_structure',
                    args: [[]],
                    kwargs: {}
                });

                menuGroups = menuGroupsTree || [];
                return menuGroups;
            } catch (error) {
                console.warn('Could not load menu groups:', error);
                menuGroups = [];
                return menuGroups;
            }
        }

        function assignAppsToGroups(groups, allApps) {
            groups.forEach(group => {
                group.apps = allApps.filter(app => group.menu_ids.includes(app.id));

                if (group.children && group.children.length > 0) {
                    assignAppsToGroups(group.children, allApps);
                }
            });
        }

        // Quita ramas sin apps visibles para el usuario actual: un grupo se
        // mantiene solo si tiene apps propias o algún descendiente con apps.
        function pruneEmptyGroups(groups) {
            return groups.filter(group => {
                if (group.children && group.children.length > 0) {
                    group.children = pruneEmptyGroups(group.children);
                }
                const hasApps = group.apps && group.apps.length > 0;
                const hasChildren = group.children && group.children.length > 0;
                return hasApps || hasChildren;
            });
        }

        function getUngroupedApps(groups, allApps) {
            const groupedIds = new Set();

            function collectGroupedIds(groups) {
                groups.forEach(group => {
                    group.menu_ids.forEach(id => groupedIds.add(id));
                    if (group.children && group.children.length > 0) {
                        collectGroupedIds(group.children);
                    }
                });
            }

            collectGroupedIds(groups);
            return allApps.filter(app => !groupedIds.has(app.id));
        }

        return {
        	getCurrentApp () {
        		return menu.getCurrentApp();
        	},
        	getAppsMenuItems() {
				const menuItems = computeAppsAndMenuItems(
					menu.getMenuAsTree('root')
				)
				const apps = menuItems.apps;
				const menuConfig = JSON.parse(
					user.settings?.homemenu_config || 'null'
				);
				if (menuConfig) {
                    reorderApps(apps, menuConfig);
				}
        		return apps;
			},
			async getMenuGroups() {
                const groups = await loadMenuGroups();
                const allApps = this.getAppsMenuItems();

                assignAppsToGroups(groups, allApps);

                return pruneEmptyGroups(groups);
            },
            async getUngroupedApps() {
                const groups = await loadMenuGroups();
                const allApps = this.getAppsMenuItems();

                return getUngroupedApps(groups, allApps);
            },
			selectApp(app) {
				menu.selectMenu(app);
			}
        };
    },
};

registry.category("services").add("app_menu", appMenuService);
