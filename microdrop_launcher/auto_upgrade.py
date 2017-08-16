import json
import logging

import pip_helpers as pih

import conda_helpers as ch


logger = logging.getLogger(__name__)


def _strip_conda_menuinst_messages(conda_output):
    '''
    Strip away Conda menuinst log messages to work around [issue with
    `menuinst`][0].

    For example:

        INFO menuinst_win32:__init__(182): Menu: name: 'MicroDrop', prefix: 'C:\Users\chris\Miniconda2\envs\dropbot.py', env_name: 'dropbot.py', mode: 'None', used_mode: 'user'

    See [here][1] for more information.

    [0]: https://github.com/ContinuumIO/menuinst/issues/49
    [1]: https://groups.google.com/a/continuum.io/forum/#!topic/anaconda/RWs9of4I2KM
    '''
    return '\n'.join(line_i for line_i in conda_output.splitlines()
                     if not line_i.startswith('INFO'))


def main():
    '''
    .. versionadded:: 0.1.post62

    .. versionchanged:: 0.7.5
        Use Conda install dry-run to check for new version.
    '''
    # Upgrade `microdrop-launcher` package if there is a new version available.
    print 'Checking for `microdrop-launcher` updates',

    # Check if new version of `microdrop-launcher` would be installed.
    dry_run_response = json.loads(ch.conda_exec('install', '--dry-run',
                                                '--json',
                                                'microdrop-launcher',
                                                verbose=False))
    try:
        dry_run_unlinked, dry_run_linked = ch.install_info(dry_run_response)
    except RuntimeError, exception:
        if 'CondaHTTPError' in str(exception):
            print 'Error checking for updates - no network connection'
            return
        else:
            print 'Error checking for updates.\n{}'.format(exception)
    else:
        if dry_run_linked and [package_i
                               for package_i, channel_i in dry_run_linked
                               if 'microdrop-launcher' ==
                               package_i.split('==')[0]]:
            # A new version of the launcher is available for installation.
            print 'Upgrading to:', package_i
            install_log_json = ch.conda_exec('install', '--json',
                                             'microdrop-launcher',
                                             verbose=False)
            install_log_json = _strip_conda_menuinst_messages(install_log_json)
            install_response = json.loads(install_log_json)
            unlinked, linked = ch.install_info(install_response)
            print 'Uninstall:'
            print '\n'.join(' - `{} (from {})`'.format(package_i, channel_i)
                            for package_i, channel_i in unlinked)
            print ''
            print 'Install:'
            print '\n'.join(' - `{} (from {})`'.format(package_i, channel_i)
                            for package_i, channel_i in linked)
        else:
            # No new version of the launcher is available for installation.
            print ('Up to date: {}'
                   .format(ch.package_version('microdrop-launcher',
                                              verbose=False)
                           .get('dist_name')))


if __name__ == '__main__':
    main()
