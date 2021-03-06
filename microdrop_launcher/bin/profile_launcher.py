import datetime as dt
import functools as ft
import concurrent.futures
import logging
import pkg_resources
import re
import subprocess as sp
import sys

import gtk
import mpm
import mpm.bin
import path_helpers as ph
import pygtkhelpers.ui.dialogs as gd
import yaml

from ..dirs import AppDirs
from ..config import create_config_directory
from ..profile import (ICON_PATH, SAVED_COLUMNS, drop_version_errors,
                       environment_prompt, get_major_version, import_profile,
                       installed_major_version, launch_profile,
                       load_profiles_info, profile_major_version,
                       verify_or_create_profile_version)

logger = logging.getLogger(__name__)


class LaunchDialog(object):
    def __init__(self, df_profiles):
        self.df_profiles = df_profiles
        self.content_area = None
        self.frame = None
        self.profile_row = None
        self.return_code = None

    def import_profile(self, folder=None):
        # Display GTK dialog to select output directory.
        folder = gd.select_folder(folder=folder, title='Select MicroDrop '
                                  'profile directory')
        if folder is None:
            return

        try:
            verify_or_create_profile_version(folder)
        except RuntimeError, exception:
            # Major version in `RELEASE-VERSION` file and major version of
            # installed MicroDrop package **do not match**.
            gd.error(str(exception))
        else:
            self.df_profiles = import_profile(self.df_profiles, folder,
                                              parent=self.dialog)
            self.update_profiles_frame()

    def create_profile(self, folder=None):
        # Display GTK dialog to select output directory.
        folder = gd.select_folder(folder=folder, title='Select new MicroDrop '
                                  'profile directory')
        if folder is None:
            return
        else:
            folder = ph.path(folder).realpath()

        if folder.files() or folder.dirs():
            dialog = gtk.MessageDialog(type=gtk.MESSAGE_QUESTION)
            dialog.set_icon_from_file(ICON_PATH)
            dialog.set_title('Confirm overwrite')
            dialog.set_markup('Directory is not empty.\n\nOverwrite?')
            dialog.add_buttons(gtk.STOCK_YES, gtk.RESPONSE_YES,
                               gtk.STOCK_NO, gtk.RESPONSE_NO)
            response = dialog.run()
            dialog.destroy()
            if response == gtk.RESPONSE_NO:
                return
        try:
            create_config_directory(output_dir=folder, overwrite=True)
        except IOError, exception:
            print >> sys.stderr, exception
            return
        else:
            folder.joinpath('devices').makedirs_p()
            folder.joinpath('plugins').makedirs_p()

        self.df_profiles = self.df_profiles.append({'path': folder,
                                                    'major_version':
                                                    installed_major_version()},
                                                   ignore_index=True)
        self.df_profiles.drop_duplicates(subset=['path'], inplace=True)
        self.update_profiles_frame()

    def update_profiles_frame(self):
        def on_launch_clicked(profile_row_i):
            self.dialog.hide()
            self.profile_row = profile_row_i.copy()
            self.return_code = launch_profile_row(profile_row_i)
            if self.return_code is None:
                self.frame = None
                self.run()
            elif self.return_code == 0:
                profile_row_i.used_timestamp = str(dt.datetime.now())

        def on_remove_clicked(profile_row_i):
            dialog = gtk.MessageDialog(type=gtk.MESSAGE_QUESTION)
            dialog.set_icon_from_file(ICON_PATH)
            dialog.set_title('Remove profile')
            RESPONSE_REMOVE, RESPONSE_REMOVE_WITH_DATA, RESPONSE_CANCEL = \
                range(3)
            dialog.add_buttons('_Remove', RESPONSE_REMOVE, 'Remove with _data',
                               RESPONSE_REMOVE_WITH_DATA, 'Can_cel',
                               RESPONSE_CANCEL)
            dialog.set_markup('Remove the following profile from list?\n\n'
                              '    {}\n\n'
                              '<b>"Remove with data"</b> removes profile from '
                              'list <b>and deletes the profile '
                              'directory</b>.'.format(profile_row_i.path))
            response = dialog.run()
            dialog.destroy()
            if response not in (RESPONSE_REMOVE, RESPONSE_REMOVE_WITH_DATA):
                return
            try:
                if response == RESPONSE_REMOVE_WITH_DATA:
                    dialog = gtk.MessageDialog(type=gtk.MESSAGE_QUESTION)
                    dialog.set_icon_from_file(ICON_PATH)
                    dialog.set_title('Confirm profile delete')
                    dialog.set_markup('Remove profile data (cannot be '
                                      'undone)?')
                    dialog.add_buttons(gtk.STOCK_YES, gtk.RESPONSE_YES,
                                       gtk.STOCK_NO, gtk.RESPONSE_NO)
                    response = dialog.run()
                    dialog.destroy()
                    if response == gtk.RESPONSE_YES:
                        ph.path(profile_row_i.path).rmtree()
                    else:
                        return
            except Exception, exception:
                gd.error(str(exception))
            finally:
                self.df_profiles = (self.df_profiles
                                    .loc[self.df_profiles.path !=
                                         profile_row_i.path].copy())
            self.update_profiles_frame()

        if self.frame is not None:
            self.content_area.remove(self.frame)
        drop_version_errors(self.df_profiles, missing=False, mismatch=True,
                            inplace=True)
        self.frame = get_profiles_table(self.df_profiles, on_launch_clicked,
                                        on_remove_clicked)
        self.content_area.pack_start(self.frame, expand=True, fill=True, padding=10)
        self.content_area.reorder_child(self.frame, 0)
        self.dialog.show()

        def _resize_dialog(*args):
            # Resize dialog to fit allocated size of updated table.
            x, y, width, height = (self.frame.get_child().get_child()
                                   .get_child().get_allocation())
            self.dialog.set_size_request(max(520, width + 30), 320)

        # Queue resize request to allow table to be allocated before resizing.
        gtk.idle_add(_resize_dialog)

    def run(self):
        self.dialog = gtk.Dialog()
        self.dialog.set_icon_from_file(ICON_PATH)
        self.dialog.set_title('MicroDrop Profile Manager')
        self.content_area = self.dialog.get_content_area()

        buttons_area = gtk.HBox()
        buttons_box = gtk.HButtonBox()
        button_import = gtk.Button('_Import...')
        button_create = gtk.Button('_Create...')
        button_import.connect('clicked', lambda *args:
                              self.import_profile(self.df_profiles
                                                  .path.get(0)))
        button_create.connect('clicked', lambda *args:
                              self.create_profile(self.df_profiles.path
                                                  .get(0)))
        for button_i in (button_import, button_create):
            buttons_box.pack_end(button_i, expand=False, fill=False)
        buttons_area.pack_end(buttons_box, expand=False, fill=False)
        buttons_area.show_all()
        self.content_area.pack_end(buttons_area, expand=False, fill=False)

        self.update_profiles_frame()
        self.dialog.props.resizable = False
        self.dialog.run()

        return self.profile_row


def get_profiles_table(df_profiles, launch_callback, remove_callback,
                       short_threshold=40):
    def short_path(path_i):
        base_i, name_i = ph.path(path_i).splitpath()

        if len(base_i) > short_threshold:
            base_i = ph.path(base_i[:short_threshold]).parent.joinpath('...')
        return base_i.joinpath(name_i)

    grid_columns = ['path', 'major_version']

    # One header row plus one row per profile
    # One column for each column in `grid_columns`, plus two columns for launch
    # and remove buttons, respectively.
    table = gtk.Table(df_profiles.shape[0] + 1, len(grid_columns) + 2)

    for i, column_i in enumerate(grid_columns):
        label_i = gtk.Label()
        label_i.set_markup('<b>{}</b>'.format(column_i))
        table.attach(label_i, left_attach=i, right_attach=i + 1, top_attach=0,
                     bottom_attach=1, xpadding=5, ypadding=5,
                     xoptions=gtk.SHRINK, yoptions=gtk.SHRINK)

    for i, (ix, row_i) in enumerate(df_profiles.iterrows()):
        row_kwargs = dict(top_attach=i + 1, bottom_attach=i + 2,
                          xpadding=5, ypadding=5,
                          xoptions=gtk.SHRINK | gtk.FILL, yoptions=gtk.SHRINK)
        for j, column_ij in enumerate(grid_columns):
            if column_ij == 'path':
                label_ij = gtk.Label(short_path(row_i.path))
                timestamp_str_ij = re.sub(r'\.\d+$', '',
                                          str(row_i.used_timestamp))
                label_ij.set_tooltip_text('{}\nLast used: {}'
                                          .format(row_i.path,
                                                  timestamp_str_ij))
                label_ij.set_alignment(0, .5)
            else:
                label_ij = gtk.Label(row_i[column_ij])
            table.attach(label_ij, left_attach=j, right_attach=j + 1,
                         **row_kwargs)

        button_launch_i = gtk.Button('Launch')
        button_open_i = gtk.Button('Open')
        button_prompt_i = gtk.Button('Prompt')
        button_remove_i = gtk.Button('Remove')

        # Use `functools.partial` to bind parameters (through [currying][1])
        # for current profile to callback functions.
        #
        # Without [currying][1], all callbacks would *erroneously* be called
        # using references to parameters of the **last** profile processed.
        #
        # [1]: https://mtomassoli.wordpress.com/2012/03/18/currying-in-python/
        on_launch_clicked = ft.partial(lambda row, *args:
                                       launch_callback(row), row_i)
        on_open_clicked = ft.partial(lambda profile_path, *args:
                                     profile_path.launch(),
                                     ph.path(row_i.path))
        on_prompt_clicked = ft.partial(lambda profile_path, *args:
                                       environment_prompt(profile_path),
                                       row_i.path)
        on_remove_clicked = ft.partial(lambda row, *args: remove_callback(row),
                                       row_i)

        button_launch_i.connect('clicked', on_launch_clicked)
        button_open_i.connect('clicked', on_open_clicked)
        button_prompt_i.connect('clicked', on_prompt_clicked)
        button_remove_i.connect('clicked', on_remove_clicked)
        # button_remove_i.connect('clicked', lambda
        for button_ij, j in zip((button_launch_i, button_open_i,
                                 button_prompt_i, button_remove_i),
                                range(j + 1, j + 5)):
            table.attach(button_ij, left_attach=j, right_attach=j + 1,
                         **row_kwargs)

    scrolled_window = gtk.ScrolledWindow()
    scrolled_window.set_policy(hscrollbar_policy=gtk.POLICY_AUTOMATIC,
                               vscrollbar_policy=gtk.POLICY_ALWAYS)
    scrolled_window.add_with_viewport(table)
    scrolled_window.props.shadow_type = gtk.SHADOW_NONE
    scrolled_window.get_child().props.shadow_type = gtk.SHADOW_NONE
    frame = gtk.Frame(label='Select profile to launch')
    frame.add(scrolled_window)
    # frame.props.shadow_type = gtk.SHADOW_NONE
    frame.show_all()
    return frame


def launch_profile_row(profile_row_i):
    try:
        return_code = launch_profile(profile_row_i.path)
    except Exception, exception:
        dialog = gtk.MessageDialog(type=gtk.MESSAGE_ERROR,
                                   message_format=str(exception))
        dialog.set_icon_from_file(ICON_PATH)
        dialog.set_title('Error launching profile')
        dialog.add_buttons(gtk.STOCK_OK, gtk.RESPONSE_OK)
        dialog.run()
        dialog.destroy()
    else:
        return return_code


def parse_args(args=None):
    '''Parses arguments, returns (options, args).'''
    from argparse import ArgumentParser

    if args is None:
        args = sys.argv

    major_version = get_major_version(pkg_resources
                                      .get_distribution('microdrop').version)
    # Look up MicroDrop application directories based on major version.
    microdrop_env_dirs = AppDirs('MicroDrop', version=major_version)
    # Construct path to list of profiles based on user configuration directory.
    default_profiles_path = (microdrop_env_dirs.user_config_dir
                             .joinpath('profiles.yml'))

    parser = ArgumentParser(description='MicroDrop {} profile manager'
                            .format(major_version),
                            parents=[mpm.bin.LOG_PARSER])

    parser.add_argument('-f', '--profiles-path', type=ph.path,
                        help='Path to profiles list (default=%(default)s)',
                        default=default_profiles_path)
    parser.add_argument('--default', action='store_true',
                        help='Launch most recently used profile.')
    parser.add_argument('--no-auto', action='store_true',
                        help='If not set and there is only a single profile, '
                        'MicroDrop is launched using the profile.')
    parser.add_argument('--no-upgrade', action='store_true',
                        help='Do not check for package upgrade.')

    args = parser.parse_args()

    return args


def main():
    args = parse_args()
    logging.basicConfig(level=getattr(logging, args.log_level.upper()))

    # Load list of profiles from file.
    #
    # If file does not exist or list is empty, the profile list is initialized
    # with the default profile directory path.
    df_profiles = load_profiles_info(args.profiles_path)
    drop_version_errors(df_profiles, missing=False, mismatch=True,
                        inplace=True)

    # Save most recent list of profiles to disk.
    with args.profiles_path.open('w') as output:
        profiles_str = yaml.dump(df_profiles[SAVED_COLUMNS].astype(str)
                                 .to_dict('records'), default_flow_style=False)
        output.write(profiles_str)

    # Look up major version of each profile.
    df_profiles['major_version'] = df_profiles.path.map(profile_major_version)

    # Perform the following tasks in the background:
    #
    #  - Upgrade `microdrop-launcher` package
    #  - Cache latest `microdrop` package version
    with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
        def _auto_upgrade():
            process = sp.Popen([sys.executable, '-m',
                                'microdrop_launcher.auto_upgrade'])

            return process.communicate()

        def _cache_latest_microdrop_version():
            process = sp.Popen([sys.executable, '-m',
                                'microdrop_launcher.microdrop_version'])

            return process.communicate()

        def _launch(args, df_profiles):
            if args.default or (not args.no_auto and df_profiles.shape[0] == 1):
                # Launch MicroDrop with most recently used (or only available) profile.
                return_code = launch_profile_row(df_profiles.iloc[0])
                if return_code == 0:
                    df_profiles.used_timestamp[0] = str(dt.datetime.now())
            else:
                # Display dialog to manage profiles or launch a profile.
                launch_dialog = LaunchDialog(df_profiles)
                launch_dialog.run()
                return_code = launch_dialog.return_code
                df_profiles = launch_dialog.df_profiles

            # Save most recent list of profiles to disk (most recently used first).
            #
            # List can be changed using dialog by:
            #  - Creating a new profile.
            #  - Importing a profile.
            #  - Updating used timestamp by launching a profile.
            df_profiles = df_profiles.astype(str)
            df_profiles.loc[df_profiles.used_timestamp == 'nan',
                            'used_timestamp'] = ''
            df_profiles.sort_values('used_timestamp', ascending=False,
                                    inplace=True)

            with args.profiles_path.open('w') as output:
                profiles_str = yaml.dump(df_profiles[SAVED_COLUMNS]
                                        .to_dict('records'),
                                         default_flow_style=False)
                output.write(profiles_str)
            return return_code

        futures = []
        if not args.no_upgrade:
            upgrade_future = executor.submit(_auto_upgrade)
            microdrop_version_future = \
                executor.submit(_cache_latest_microdrop_version)
            futures.extend([upgrade_future, microdrop_version_future])
        launch_future = executor.submit(_launch, args, df_profiles)
        futures.append(launch_future)
        concurrent.futures.wait(futures)
        return launch_future.result()


if __name__ == '__main__':
    return_code = main()
    raise SystemExit(return_code)
