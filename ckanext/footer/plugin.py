from __future__ import annotations
import datetime
import ckan.plugins as plugins
import ckan.plugins.toolkit as toolkit, config
from ckanext.related_resources.models.related_resources import RelatedResources as related_resources
from ckanext.footer.controller.monthlycount import MonthlyCountController #DATASET_NAME, RESOURCE_NAME, OWNER_ORG
import ckan.logic as logic
import click
from flask import Blueprint, render_template, session, has_request_context,redirect, url_for, jsonify
import asyncio
from collections import defaultdict
from ckanext.footer.controller.display_mol_image import FooterController
from ckan.common import request
import logging
import json
from typing import Any, Dict

log = logging.getLogger(__name__)

get_action = logic.get_action

CONFIG_GET_MOLECULES_PER_PAGE = "ckanext.footer.molecules_per_page"


class FooterPlugin(plugins.SingletonPlugin):
    plugins.implements(plugins.IConfigurer)
    plugins.implements(plugins.IBlueprint)
    plugins.implements(plugins.ITemplateHelpers)
    plugins.implements(plugins.IFacets, inherit=True)
    plugins.implements(plugins.IPackageController, inherit=True)
    plugins.implements(plugins.IRoutes,inherit=True)

    def update_config(self, config_):
        toolkit.add_template_directory(config_, 'templates')
        toolkit.add_public_directory(config_, 'public')
        toolkit.add_resource('public/statics', 'footer')

    def get_blueprint(self):
        blueprint = Blueprint(self.name, self.__module__)

        blueprint.add_url_rule(
            u'/search_bar',
            u'search_bar',
            FooterController.searchbar,
            methods=['GET', 'POST']
        )

        blueprint.add_url_rule(
                        '/moleculesearch',
                        'molecule_view_self',
                        FooterController.search_molecule,
                        methods=['GET', 'POST'] )

        blueprint.add_url_rule(
            u'/dataset',
            u'display_mol_image',
            FooterController.display_search_mol_image,
            methods=['GET', 'POST'])

        return blueprint

    # ITemplate Helpers
    def get_helpers(self):
        return {'footer': FooterController.display_search_mol_image,
                'searchbar': FooterController.searchbar,
                'mol_package_list': FooterController.mol_dataset_list,
                'package_list_for_every_inchi': FooterController.package_show_dict,
                'get_molecule_data': FooterController.get_molecule_data,
                'package_list': FooterPlugin.molecule_view_search,
                #'get_facet_field_list':FooterController.get_facet_field_list_sent,
                #'package_list': FooterController.molecule_view_list
               }


    @staticmethod
    def before_search(search_params: Dict[str, Any]) -> Dict[str, Any]:
        # Example modification: add a logging for debug and modify query if empty
        if search_params.get('q', '') == '':
            search_params['q'] = '*:*'  # default query if none provided
        if not has_request_context():
            return search_params
        try:
            session['initial_search_params'] = search_params
        except Exception:
            pass
        return search_params

    @staticmethod
    def after_search(search_results: Dict[str, Any], search_params: Dict[str, Any]) -> Dict[str, Any]:
        search_params = search_params.copy()
        if search_params['q'] == '*:*':
            search_params_result = None
        else:
            search_params_result = search_params

        session['search_results_final'] = search_results
        session['search_params'] = search_params_result
        session.save()

        return search_results

    @staticmethod
    def molecule_view_search():
        packages_list = {'count': '', 'results': '', 'facets': ''}
        search_params = None

        return packages_list, search_params


# New Extension
DATASET_NAME = 'site-monthly-counts'
RESOURCE_NAME = 'monthly_counts'
OWNER_ORG =  'ckanext.monthlycounts.owner_org' # can be overridden via ini

def monthlycounts_list(context, data_dict):
    """
    CKAN Action:
    /api/3/action/monthlycounts_list

    Returns the monthly counts from the Datastore resource as JSON.
    Accepts optional 'limit' and 'sort' in data_dict.
    """
    # Authorization: reuse 'sysadmin-only' semantics, or define your own
    # toolkit.check_access('sysadmin', context, data_dict)
    context['ignore_auth'] = True

    # Get resource id (from the same controller you already use)
    res_id = MonthlyCountController._get_or_bootstrap_resource(context)

    limit = int(data_dict.get('limit', 10000))
    sort = data_dict.get('sort', 'snapshot_date desc, org_name asc')

    search_result = toolkit.get_action('datastore_search')(context, {
        'resource_id': res_id,
        'limit': limit,
        'sort': sort,
    })

    # Shape the response like other CKAN actions
    return {
        'resource_id': res_id,
        'total': search_result.get('total', 0),
        'records': search_result.get('records', []),
    }


class MonthlyCountsAdminPlugin(plugins.SingletonPlugin):
    """Adds /ckan-admin/monthly-counts (admin-only) and snapshot helpers."""
    plugins.implements(plugins.IConfigurer)
    plugins.implements(plugins.IBlueprint)
    plugins.implements(plugins.IConfigurable)
    plugins.implements(plugins.IClick)
    plugins.implements(plugins.IActions)  # <-- add this

    def update_config(self, config):
        toolkit.add_template_directory(config, 'templates')


    def configure(self, config):
        global DATASET_NAME, RESOURCE_NAME, OWNER_ORG
        DATASET_NAME = config.get('ckanext.monthlycounts.dataset_name', DATASET_NAME)
        RESOURCE_NAME = config.get('ckanext.monthlycounts.resource_name', RESOURCE_NAME)
        OWNER_ORG = config.get('ckanext.monthlycounts.owner_org', OWNER_ORG)

        # push settings to controller globals
        MonthlyCountController.DATASET_NAME = DATASET_NAME
        MonthlyCountController.RESOURCE_NAME = RESOURCE_NAME
        MonthlyCountController.OWNER_ORG = OWNER_ORG

    def get_actions(self):
        # expose one action: monthlycounts_list
        return {
            'monthlycounts_list': monthlycounts_list
        }
    # --- Admin page blueprint ---
    def get_blueprint(self):
        bp = Blueprint('monthly_counts_admin', __name__)

        @bp.route('/ckan-admin/monthly-counts', methods=['GET', 'POST'])
        def monthly_counts_admin():
            context = {
                'user': toolkit.c.user,
                'auth_user_obj': toolkit.c.userobj,
                'ignore_auth': False,
            }
            log.debug('monthly_counts_admin: context user=%s ignore_auth=%s',
                      context.get('user'), context.get('ignore_auth'))

            res_id = MonthlyCountController._get_or_bootstrap_resource(context)

            if request.method == 'POST' and request.form.get('do_snapshot'):
                try:
                    MonthlyCountController._snapshot_now(context)
                    toolkit.h.flash_success('Snapshot created successfully.')
                    log.debug('monthly_counts_admin: snapshot success')
                    return redirect(url_for('monthly_counts_admin.monthly_counts_admin'))
                except Exception as e:
                    log.exception('monthly_counts_admin: snapshot failed: %s', e)
                    toolkit.h.flash_error(f'Snapshot failed: {e}')

            rows = toolkit.get_action('datastore_search')(context, {
                'resource_id': res_id,
                'limit': 10000,
                'sort': 'snapshot_date desc, org_name asc'
            }).get('records', [])

            return toolkit.render('admin/monthly_counts.html', extra_vars={'rows': rows})

        #return bp

        @bp.route('/monthly-counts/data', methods=['GET'])
        def monthly_counts_data():
            context = {
                'ignore_auth': True,
                'user': toolkit.c.user or 'visitor',  # user is mostly irrelevant if ignore_auth=True
            }

            # Fetch the datastore resource
            res_id = MonthlyCountController._get_or_bootstrap_resource(context)

            result = toolkit.get_action('datastore_search')(context, {
                'resource_id': res_id,
                'limit': 10000,
                'sort': 'snapshot_date desc, org_name asc'
            })

            # Only sends the latest date nformation based on the
            records = result['records']
            by_date = defaultdict(list)
            for row in records:
                by_date[row['snapshot_date']].append(row)

            latest_date = max(by_date.keys())
            latest_records = by_date[latest_date]

            results = {}

            for entry in latest_records:
                name = entry["org_name"]
                count = entry["dataset_count"]
                # results['Snapshot Date'] = latest_date

                # Normal cases
                if name not in ("__TOTAL__Datasets", "Total Molecules"):
                    # Make key like: ICSD_dataset_count
                    key = f"{name.replace(' ', '_')}_dataset_count"
                    results[key] = count

                # Special cases
                if name == "__TOTAL__Datasets":
                    results["Total_datasets"] = count

                if name == "Total Molecules":
                    results["Total_Molecules"] = count

            log.debug(f"Result that wee need {results}")

            return jsonify(results)

        return bp


    # --- CLI (ckan monthlycounts snapshot) ---
    def get_commands(self):
        import click

        @click.group()
        def monthlycounts():
            """Monthly dataset counting utilities (admin)."""
            log.debug('CLI monthlycounts group invoked')

        @monthlycounts.command()
        @click.option('--date', 'date_str', default=None,
                      help='Snapshot date (YYYY-MM-DD). Defaults to today.')
        def snapshot(date_str):
            """Write a snapshot row-set (total + per-org) to the Datastore."""
            log.debug('CLI snapshot: start date_str=%s', date_str)
            context = {
                'ignore_auth': True,
                'user': toolkit.config.get('ckan.tracking_user', 'admin')
            }
            try:
                snap_date = datetime.date.fromisoformat(date_str) if date_str else None
            except Exception:
                log.debug('CLI snapshot: invalid date_str=%s falling back to today', date_str)
                snap_date = None

            # Ensure the target resource exists before upsert
            res_id = MonthlyCountController._get_or_bootstrap_resource(context)

            MonthlyCountController._snapshot_now(context, snap_date)
            log.debug('CLI snapshot: completed OK')
            click.echo('Monthly snapshot written.')

        return [monthlycounts]