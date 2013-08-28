#    Copyright (C) 2008-2011  Oliver Gerlich <oliver.gerlich@gmx.de>
#    Copyright (C) 2011  Jean-Philippe Fleury <contact@jpfleury.net>
#
#    This program is free software; you can redistribute it and/or modify
#    it under the terms of the GNU General Public License as published by
#    the Free Software Foundation; either version 2 of the License, or
#    (at your option) any later version.
#
#    This program is distributed in the hope that it will be useful,
#    but WITHOUT ANY WARRANTY; without even the implied warranty of
#    MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
#    GNU General Public License for more details.
#
#    You should have received a copy of the GNU General Public License
#    along with this program; if not, write to the Free Software
#    Foundation, Inc., 51 Franklin Street, Fifth Floor, Boston, MA  02110-1301, USA.


#
# Main classes:
# - FileSearchWindowHelper (is instantiated by FileSearchPlugin for every window, and holds the search dialog)
# - FileSearcher (is instantiated by FileSearchWindowHelper for every search, and holds the result tab)
#
# Helper classes:
# - RecentList (holds list of recently-selected search directories, for search dialog)
# - SearchQuery (holds all parameters for a search; also, can read and write these from/to GConf)
#

import os
import urllib
import dircache
from gettext import gettext, translation
import locale

from gi.repository import Gedit, GObject, Gtk, Gdk, GConf, Gio, Pango

# translation
APP_NAME = 'file-search'
LOCALE_PATH = os.path.dirname(__file__) + '/locale'
t = translation(APP_NAME, LOCALE_PATH, fallback=True)
_ = t.ugettext
ngettext = t.ungettext

# set gettext domain for GtkBuilder
locale.bindtextdomain(APP_NAME, LOCALE_PATH)

from searcher import SearchProcess, buildQueryRE


ui_str = """<ui>
  <menubar name="MenuBar">
    <menu name="SearchMenu" action="Search">
      <placeholder name="SearchOps_2">
        <menuitem name="FileSearch" action="FileSearch"/>
      </placeholder>
    </menu>
  </menubar>
</ui>
"""

gconfBase = '/apps/gedit-2/plugins/file-search'


class RecentList:
    """
    Encapsulates a gtk.ListStore that stores a generic list of "most recently used entries"
    """
    def __init__ (self, gclient, confKey, maxEntries = 10):
        self.gclient = gclient
        self.confKey = gconfBase + "/" + confKey
        self.store = Gtk.ListStore(str, bool, bool) # text, save-to-gconf, is-separator
        self._maxEntries = maxEntries
        self._haveSeparator = False

        rawValue = self.gclient.get(self.confKey)
        valueList = rawValue.get_list()
        valueList.reverse()
        for gconfValue in valueList:
            e = gconfValue.get_string()
            if e and len(e) > 0:
                decodedName = urllib.unquote(e)
                self.add(decodedName, False)

        # TODO: also listen for gconf changes, and reload the list then

    def add (self, entrytext, doStore=True):
        "Add an entry that was just used."
        if type(entrytext) == unicode:
            entrytext = entrytext.encode("utf-8")
        assert(type(entrytext) == str)

        for row in self.store:
            if row[0] == entrytext:
                it = self.store.get_iter(row.path)
                self.store.remove(it)

        treeiter = self.store.prepend()
        self.store.set_row(treeiter, [entrytext, True, False])

        if len(self.store) > self._maxEntries:
            it = self.store.get_iter(self.store[-1].path)
            self.store.remove(it)

        if doStore:
            entries = []
            for e in self.store:
                if not(e[1]):
                    continue
                assert(type(e[0]) == str)
                encodedName = urllib.quote(e[0])
                entries.append(encodedName)
            self._setGconfStringList(self.confKey, entries)

    def _setGconfStringList (self, path, valueList):
        "workaround for bgo#681433: GConf.Client.set_list() is not available in Python"
        import subprocess
        cmd = [ "gconftool-2", "--type", "list", "--list-type", "string", "--set", path, "[%s]" % ",".join(valueList) ]
        subprocess.call(cmd)


    def addTemp (self, entrytext):
        if not(self._haveSeparator):
            self.store.append(["(_sep_)", False, True])
            self._haveSeparator = True
        self.store.append([entrytext, False, False])

    def resetTemps (self):
        for row in self.store:
            if not(row[1]):
                it = self.store.get_iter(row.path)
                self.store.remove(it)
        self._haveSeparator = False

    def separatorRowFunc (self, model, it, data):
        return model[it][2]

    def isEmpty (self):
        return (len(self.store) == 0)

    def topEntry (self):
        if self.isEmpty():
            return None
        else:
            return self.store[0][0]


class SearchQuery:
    """
    Contains all parameters for a single search action.
    """
    def __init__ (self):
        self.text = ''
        self.directory = ''
        self.caseSensitive = True
        self.wholeWord = False
        self.isRegExp = False
        self.includeSubfolders = True
        self.excludeHidden = True
        self.excludeBackup = True
        self.excludeVCS = True
        self.selectFileTypes = False
        self.fileTypeString = ''

    def parseFileTypeString (self):
        "Returns a list with the separate file globs from fileTypeString"
        return self.fileTypeString.split()

    def loadDefaults (self, gclient):
        try:
            self.caseSensitive = gclient.get_without_default(gconfBase+"/case_sensitive").get_bool()
        except:
            self.caseSensitive = True

        try:
            self.wholeWord = gclient.get_without_default(gconfBase+"/whole_word").get_bool()
        except:
            self.wholeWord = False

        try:
            self.isRegExp = gclient.get_without_default(gconfBase+"/is_reg_exp").get_bool()
        except:
            self.isRegExp = False

        try:
            self.includeSubfolders = gclient.get_without_default(gconfBase+"/include_subfolders").get_bool()
        except:
            self.includeSubfolders = True

        try:
            self.excludeHidden = gclient.get_without_default(gconfBase+"/exclude_hidden").get_bool()
        except:
            self.excludeHidden = True

        try:
            self.excludeBackup = gclient.get_without_default(gconfBase+"/exclude_backup").get_bool()
        except:
            self.excludeBackup = True

        try:
            self.excludeVCS = gclient.get_without_default(gconfBase+"/exclude_vcs").get_bool()
        except:
            self.excludeVCS = True

        try:
            self.selectFileTypes = gclient.get_without_default(gconfBase+"/select_file_types").get_bool()
        except:
            self.selectFileTypes = False

    def storeDefaults (self, gclient):
        gclient.set_bool(gconfBase+"/case_sensitive", self.caseSensitive)
        gclient.set_bool(gconfBase+"/whole_word", self.wholeWord)
        gclient.set_bool(gconfBase+"/is_reg_exp", self.isRegExp)
        gclient.set_bool(gconfBase+"/include_subfolders", self.includeSubfolders)
        gclient.set_bool(gconfBase+"/exclude_hidden", self.excludeHidden)
        gclient.set_bool(gconfBase+"/exclude_backup", self.excludeBackup)
        gclient.set_bool(gconfBase+"/exclude_vcs", self.excludeVCS)
        gclient.set_bool(gconfBase+"/select_file_types", self.selectFileTypes)


class FileSearchWindowHelper(GObject.Object, Gedit.WindowActivatable):
    __gtype_name__ = "FileSearchWindowHelper"
    window = GObject.property(type=Gedit.Window)

    def __init__(self):
        GObject.Object.__init__(self)

    def do_activate(self):
        #print "file-search: plugin created for", window
        self._window = self.window
        self._dialog = None
        self._bus = self._window.get_message_bus()
        self._fileBrowserContacted = False
        self.searchers = [] # list of existing SearchProcess instances

        self.gclient = GConf.Client.get_default()
        self.gclient.add_dir(gconfBase, GConf.ClientPreloadType.PRELOAD_NONE)

        self._lastSearchTerms = RecentList(self.gclient, "recent_search_terms")
        self._lastDirs = RecentList(self.gclient, "recent_dirs")
        self._lastTypes = RecentList(self.gclient, "recent_types")

        if self._lastTypes.isEmpty():
            # add some default file types
            self._lastTypes.add('*.C *.cpp *.cxx *.h *.hpp')
            self._lastTypes.add('*.c *.h')
            self._lastTypes.add('*.py')
            self._lastTypes.add('*')

        self._lastDir = None
        self._autoCompleteList = None

        self._lastClickIter = None # TextIter at position of last right-click or last popup menu

        self._insert_menu()

        self._window.connect_object("destroy", FileSearchWindowHelper.destroy, self)
        self._window.connect_object("tab-added", FileSearchWindowHelper.onTabAdded, self)
        self._window.connect_object("tab-removed", FileSearchWindowHelper.onTabRemoved, self)

    def do_deactivate(self):
        #print "file-search: plugin stopped for", self._window
        self.destroy()

    def destroy (self):
        #print "have to destroy %d existing searchers" % len(self.searchers)
        for s in self.searchers[:]:
            s.destroy()
        self._window = None

    def do_update_state(self):
        # Called whenever the window has been updated (active tab
        # changed, etc.)
        #print "file-search: plugin update for", self._window
        if not(self._fileBrowserContacted):
            self._fileBrowserContacted = True
            self._addFileBrowserMenuItem()

    def onTabAdded (self, tab):
        handlerIds = []
        handlerIds.append( tab.get_view().connect_object("button-press-event", FileSearchWindowHelper.onButtonPress, self, tab) )
        handlerIds.append( tab.get_view().connect_object("popup-menu", FileSearchWindowHelper.onPopupMenu, self, tab) )
        handlerIds.append( tab.get_view().connect_object("populate-popup", FileSearchWindowHelper.onPopulatePopup, self, tab) )
        tab.set_data("file-search-handlers", handlerIds) # store list of handler IDs so we can later remove the handlers again

    def onTabRemoved (self, tab):
        handlerIds = tab.get_data("file-search-handlers")
        if handlerIds:
            for h in handlerIds:
                tab.get_view().handler_disconnect(h)
            tab.set_data("file-search-handlers", None)

    def onButtonPress (self, event, tab):
        if event.button == 3:
            (bufX, bufY) = tab.get_view().window_to_buffer_coords(Gtk.TextWindowType.TEXT, int(event.x), int(event.y))
            self._lastClickIter = tab.get_view().get_iter_at_location(bufX, bufY)

    def onPopupMenu (self, tab):
        insertMark = tab.get_document().get_insert()
        self._lastClickIter = tab.get_document().get_iter_at_mark(insertMark)

    def onPopulatePopup (self, menu, tab):
        # add separator:
        sepMi = Gtk.SeparatorMenuItem.new()
        sepMi.show()
        menu.prepend(sepMi)

        # first check if user has selected some text:
        selText = ""
        currDoc = tab.get_document()
        selectionIters = currDoc.get_selection_bounds()
        if selectionIters and len(selectionIters) == 2:
            # Only use selected text if it doesn't span multiple lines:
            if selectionIters[0].get_line() == selectionIters[1].get_line():
                selText = selectionIters[0].get_text(selectionIters[1])

        # if no text is selected, use current word under cursor:
        if not(selText) and self._lastClickIter:
            startIter = self._lastClickIter.copy()
            if not(startIter.starts_word()):
                startIter.backward_word_start()
            endIter = startIter.copy()
            if endIter.inside_word():
                endIter.forward_word_end()
            selText = startIter.get_text(endIter)

        # add actual menu item:
        if selText:
            menuSelText = selText.decode("utf-8")
            if len(menuSelText) > 30:
                menuSelText = menuSelText[:30] + u"\u2026" # ellipsis character
            menuText = _('Search files for "%s"') % menuSelText
        else:
            menuText = _('Search files...')
        mi = Gtk.MenuItem.new_with_label(menuText)
        mi.connect_object("activate", FileSearchWindowHelper.onMenuItemActivate, self, selText)
        mi.show()
        menu.prepend(mi)

    def onMenuItemActivate (self, searchText):
        self.openSearchDialog(searchText)

    def _addFileBrowserMenuItem (self):
        fbAction = Gtk.Action('search-files-plugin', _("Search files..."), _("Search in all files in a directory"), None)
        try:
            self._bus.send_sync('/plugins/filebrowser', 'add_context_item',
                action=fbAction, path="/FilePopup/FilePopup_Opt3")
        except StandardError, e:
            #print "failed to add file browser context menu item (%s)" % e
            return
        fbAction.connect('activate', self.onFbMenuItemActivate)

    def onFbMenuItemActivate (self, action):
        responseMsg = self._bus.send_sync('/plugins/filebrowser', 'get_view')
        fbView = responseMsg.view
        (model, rowPathes) = fbView.get_selection().get_selected_rows()

        selectedFileObj = None
        for rowPath in rowPathes:
            fileFlags = model[rowPath][3]
            isDirectory = bool(fileFlags & 1)
            if isDirectory:
                selectedFileObj = model[rowPath][2]
                break

        if selectedFileObj is None:
            msg = self._bus.send_sync('/plugins/filebrowser', 'get_root')
            selectedFileObj = msg.location
        selectedDir = selectedFileObj.get_path()

        self.openSearchDialog(searchDirectory=selectedDir)

    def registerSearcher (self, searcher):
        self.searchers.append(searcher)

    def unregisterSearcher (self, searcher):
        self.searchers.remove(searcher)

    def _insert_menu(self):
        # Get the GtkUIManager
        manager = self._window.get_ui_manager()

        # Create a new action group
        self._action_group = Gtk.ActionGroup("FileSearchPluginActions")
        self._action_group.add_actions([("FileSearch", "gtk-find", _("Search files..."),
                                         "<control><shift>F", _("Search in all files in a directory"),
                                         self.on_search_files_activate)])

        # Insert the action group
        manager.insert_action_group(self._action_group, -1)

        # Merge the UI
        self._ui_id = manager.add_ui_from_string(ui_str)

    def on_cboSearchTextEntry_changed (self, textEntry):
        """
        Is called when the search text entry is modified;
        disables the Search button whenever no search text is entered.
        """
        if textEntry.get_text() == "":
            self.builder.get_object('btnSearch').set_sensitive(False)
        else:
            self.builder.get_object('btnSearch').set_sensitive(True)

    def on_cbSelectFileTypes_toggled (self, checkbox):
        self.builder.get_object('cboFileTypeList').set_sensitive( checkbox.get_active() )

    def on_cboSearchDirectoryEntry_changed (self, entry):
        text = entry.get_text()
        if text and self._autoCompleteList != None:
            path = os.path.dirname(text)
            start = os.path.basename(text)

            self._autoCompleteList.clear()
            try:
                files = dircache.listdir(path)[:]
            except OSError:
                return
            dircache.annotate(path, files)
            for f in files:
                if f.startswith(".") and not(start.startswith(".")):
                    # show hidden dirs only if explicitly requested by user
                    continue
                if f.startswith(start) and f.endswith("/"):
                    if path == "/":
                        match = path + f
                    else:
                        match = path + os.sep + f
                    self._autoCompleteList.append([match])

    def on_btnBrowse_clicked (self, button):
        fileChooser = Gtk.FileChooserDialog(title=_("Select Directory"),
            parent=self._dialog,
            action=Gtk.FileChooserAction.SELECT_FOLDER,
            buttons = (Gtk.STOCK_CANCEL, Gtk.ResponseType.CANCEL, Gtk.STOCK_OPEN, Gtk.ResponseType.OK))
        fileChooser.set_default_response(Gtk.ResponseType.OK)
        fileChooser.set_local_only(False)
        fileChooser.set_filename( self.builder.get_object('cboSearchDirectoryEntry').get_text() )

        response = fileChooser.run()
        if response == Gtk.ResponseType.OK:
            selectedDir = os.path.normpath( fileChooser.get_filename() ) + "/"
            self.builder.get_object('cboSearchDirectoryEntry').set_text(selectedDir)
        fileChooser.destroy()

    def on_search_files_activate(self, action):
        self.openSearchDialog()

    def openSearchDialog (self, searchText = None, searchDirectory = None):
        gladeFile = os.path.join(os.path.dirname(__file__), "file-search.ui")
        self.builder = Gtk.Builder()
        self.builder.set_translation_domain(APP_NAME)
        self.builder.add_objects_from_file(gladeFile, ['searchDialog'])
        self.builder.connect_signals(self)

        self._dialog = self.builder.get_object('searchDialog')
        self._dialog.set_transient_for(self._window)

        #
        # set initial values for search dialog widgets
        #

        # get base directory of currently opened file:
        currentDocDir = None
        if self._window.get_active_tab():
            gFilePath = self._window.get_active_tab().get_document().get_location()
            if gFilePath != None:
                currentDocDir = gFilePath.get_parent().get_path()

        # find a nice default value for the search directory:
        searchDir = os.getcwdu()
        if self._lastDir != None:
            # if possible, use same directory as in last search:
            searchDir = self._lastDir
        else:
            # this is the first search since opening this Gedit window...
            if self._window.get_active_tab():
                # if ProjectMarker plugin has set a valid project root for the current file, use that:
                projectMarkerRootDir = self._window.get_active_tab().get_view().get_data("root_dir")
                if projectMarkerRootDir:
                    if projectMarkerRootDir.endswith("\n"):
                        projectMarkerRootDir = projectMarkerRootDir[:-1]
                    searchDir = projectMarkerRootDir
                else:
                    # otherwise, try to use directory of that file
                    if currentDocDir is not None:
                        searchDir = currentDocDir
            else:
                # there's no file open => fall back to Gedit's current working dir
                pass

        if searchDirectory is not None:
            searchDir = searchDirectory

        searchDir = os.path.normpath(searchDir) + "/"

        # ... and display that in the text field:
        self.builder.get_object('cboSearchDirectoryEntry').set_text(searchDir)

        # Set up autocompletion for search directory:
        completion = Gtk.EntryCompletion()
        self.builder.get_object('cboSearchDirectoryEntry').set_completion(completion)
        self._autoCompleteList = Gtk.ListStore(str)
        completion.set_model(self._autoCompleteList)
        completion.set_text_column(0)

        # Fill the drop-down part of the text field with recent dirs:
        cboLastDirs = self.builder.get_object('cboSearchDirectoryList')
        cboLastDirs.set_model(self._lastDirs.store)
        cboLastDirs.set_entry_text_column(0)
        cboLastDirs.set_row_separator_func(self._lastDirs.separatorRowFunc, None)

        self._lastDirs.resetTemps()
        if currentDocDir is not None:
            self._lastDirs.addTemp(currentDocDir)

        # TODO: the algorithm to select a good default search dir could probably be improved...

        if searchText == None:
            searchText = ""
            if self._window.get_active_tab():
                currDoc = self._window.get_active_document()
                selectionIters = currDoc.get_selection_bounds()
                if selectionIters and len(selectionIters) == 2:
                    # Only use selected text if it doesn't span multiple lines:
                    if selectionIters[0].get_line() == selectionIters[1].get_line():
                        searchText = selectionIters[0].get_text(selectionIters[1])
        self.builder.get_object('cboSearchTextEntry').set_text(searchText)

        cboLastSearches = self.builder.get_object('cboSearchTextList')
        cboLastSearches.set_model(self._lastSearchTerms.store)
        cboLastSearches.set_entry_text_column(0)

        # Fill list of file types:
        cboLastTypes = self.builder.get_object('cboFileTypeList')
        cboLastTypes.set_model(self._lastTypes.store)
        cboLastTypes.set_entry_text_column(0)

        if not(self._lastTypes.isEmpty()):
            typeListString = self._lastTypes.topEntry()
            self.builder.get_object('cboFileTypeEntry').set_text(typeListString)


        # get default values for other controls from GConf:
        query = SearchQuery()
        query.loadDefaults(self.gclient)
        self.builder.get_object('cbCaseSensitive').set_active(query.caseSensitive)
        self.builder.get_object('cbRegExp').set_active(query.isRegExp)
        self.builder.get_object('cbWholeWord').set_active(query.wholeWord)
        self.builder.get_object('cbIncludeSubfolders').set_active(query.includeSubfolders)
        self.builder.get_object('cbExcludeHidden').set_active(query.excludeHidden)
        self.builder.get_object('cbExcludeBackups').set_active(query.excludeBackup)
        self.builder.get_object('cbExcludeVCS').set_active(query.excludeVCS)
        self.builder.get_object('cbSelectFileTypes').set_active(query.selectFileTypes)
        self.builder.get_object('cboFileTypeList').set_sensitive( query.selectFileTypes )

        inputValid = False
        while not(inputValid):
            # display and run the search dialog (in a loop until all fields are correctly entered)
            result = self._dialog.run()
            if result != 1:
                self._dialog.destroy()
                return

            searchText = self.builder.get_object('cboSearchTextEntry').get_text().decode("utf-8")
            searchDir = self.builder.get_object('cboSearchDirectoryEntry').get_text()
            typeListString = self.builder.get_object('cboFileTypeEntry').get_text()

            searchDir = os.path.expanduser(searchDir)
            searchDir = os.path.normpath(searchDir) + "/"

            if searchText == "":
                print "internal error: search text is empty!"
            elif not(os.path.exists(searchDir)):
                msgDialog = Gtk.MessageDialog(self._dialog, Gtk.DialogFlags.MODAL | Gtk.DialogFlags.DESTROY_WITH_PARENT,
                    Gtk.MessageType.ERROR, Gtk.ButtonsType.OK, _("Directory does not exist"))
                msgDialog.format_secondary_text(_("The specified directory does not exist."))
                msgDialog.run()
                msgDialog.destroy()
            else:
                inputValid = True

        query.text = searchText
        query.directory = searchDir
        query.caseSensitive = self.builder.get_object('cbCaseSensitive').get_active()
        query.isRegExp = self.builder.get_object('cbRegExp').get_active()
        query.wholeWord = self.builder.get_object('cbWholeWord').get_active()
        query.includeSubfolders = self.builder.get_object('cbIncludeSubfolders').get_active()
        query.excludeHidden = self.builder.get_object('cbExcludeHidden').get_active()
        query.excludeBackup = self.builder.get_object('cbExcludeBackups').get_active()
        query.excludeVCS = self.builder.get_object('cbExcludeVCS').get_active()
        query.selectFileTypes = self.builder.get_object('cbSelectFileTypes').get_active()
        query.fileTypeString = typeListString

        self._dialog.destroy()

        #print "searching for '%s' in '%s'" % (searchText, searchDir)

        self._lastSearchTerms.add(searchText)
        self._lastDirs.add(searchDir)
        self._lastTypes.add(typeListString)
        query.storeDefaults(self.gclient)
        self._lastDir = searchDir

        searcher = FileSearcher(self._window, self, query)

class FileSearcher:
    """
    Gets a search query (and related info) and then handles everything related
    to that single file search:
    - creating a result window
    - starting grep (through SearchProcess)
    - displaying matches
    A FileSearcher object lives until its result panel is closed.
    """
    def __init__ (self, window, pluginHelper, query):
        self._window = window
        self.pluginHelper = pluginHelper
        self.pluginHelper.registerSearcher(self)
        self.query = query
        self.files = {}
        self.numMatches = 0
        self.numLines = 0
        self.wasCancelled = False
        self.searchProcess = None
        self._collapseAll = False # if true, new nodes will be displayed collapsed

        self._createResultPanel()
        self._updateSummary()

        #searchSummary = "<span size=\"smaller\" foreground=\"#585858\">searching for </span><span size=\"smaller\"><i>%s</i></span><span size=\"smaller\" foreground=\"#585858\"> in </span><span size=\"smaller\"><i>%s</i></span>" % (query.text, query.directory)
        searchSummary = "<span size=\"smaller\">" + _("searching for <i>%(keywords)s</i> in <i>%(folder)s</i>") % {'keywords': escapeMarkup(query.text), 'folder': escapeMarkup(GObject.filename_display_name(query.directory))} + "</span>"
        self.treeStore.append(None, [searchSummary, '', 0])

        self.searchProcess = SearchProcess(query, self)
        self._updateSummary()

    def handleResult (self, file, lineno, linetext):
        expandRow = False
        if not(self.files.has_key(file)):
            it = self._addResultFile(file)
            self.files[file] = it
            expandRow = True
        else:
            it = self.files[file]
        if self._collapseAll:
            expandRow = False
        self._addResultLine(it, lineno, linetext)
        if expandRow:
            path = self.treeStore.get_path(it)
            self.treeView.expand_row(path, False)
        self._updateSummary()

    def handleFinished (self):
        #print "(finished)"
        if not(self.builder):
            return

        self.searchProcess = None
        editBtn = self.builder.get_object("btnModifyFileSearch")
        editBtn.hide()
        editBtn.set_label("gtk-edit")

        self._updateSummary()

        if self.wasCancelled:
            line = "<i><span foreground=\"red\">" + _("(search was cancelled)") + "</span></i>"
        elif self.numMatches == 0:
            line = "<i>" + _("(no matching files found)") + "</i>"
        else:
            line = "<i>" + ngettext("found %d match", "found %d matches", self.numMatches) % self.numMatches
            line += ngettext(" (%d line)", " (%d lines)", self.numLines) % self.numLines
            line += ngettext(" in %d file", " in %d files", len(self.files)) % len(self.files) + "</i>"
        self.treeStore.append(None, [line, '', 0])

    def _updateSummary (self):
        summary = ngettext("<b>%d</b> match", "<b>%d</b> matches", self.numMatches) % self.numMatches
        summary += "\n" + ngettext("in %d file", "in %d files", len(self.files)) % len(self.files)
        if self.searchProcess:
            summary += u"\u2026" # ellipsis character
        self.builder.get_object("lblNumMatches").set_label(summary)


    def _createResultPanel (self):
        gladeFile = os.path.join(os.path.dirname(__file__), "file-search.ui")
        self.builder = Gtk.Builder()
        self.builder.set_translation_domain(APP_NAME)
        self.builder.add_objects_from_file(gladeFile, ['hbxFileSearchResult'])
        self.builder.connect_signals(self)
        resultContainer = self.builder.get_object('hbxFileSearchResult')

        resultContainer.set_data("filesearcher", self)

        tabTitle = self.query.text
        if len(tabTitle) > 30:
            tabTitle = tabTitle[:30] + u"\u2026" # ellipsis character 
        panel = self._window.get_bottom_panel()
        panel.add_item_with_stock_icon(resultContainer, str(self), tabTitle, "gtk-find")
        panel.activate_item(resultContainer)

        editBtn = self.builder.get_object("btnModifyFileSearch")
        editBtn.set_label("gtk-stop")

        panel.set_property("visible", True)


        self.treeStore = Gtk.TreeStore(str, str, int)
        self.treeView = self.builder.get_object('tvFileSearchResult')
        self.treeView.set_model(self.treeStore)

        self.treeView.set_search_equal_func(resultSearchCb, None)

        tc = Gtk.TreeViewColumn("File", Gtk.CellRendererText(), markup=0)
        self.treeView.append_column(tc)

    def _addResultFile (self, filename):
        dispFilename = filename
        # remove leading search directory part if present:
        if dispFilename.startswith(self.query.directory):
            dispFilename = dispFilename[ len(self.query.directory): ]
            dispFilename.lstrip("/")
        dispFilename = GObject.filename_display_name(dispFilename)

        (directory, file) = os.path.split( dispFilename )
        if directory:
            directory = os.path.normpath(directory) + "/"

        line = "%s<b>%s</b>" % (escapeMarkup(directory), escapeMarkup(file))
        it = self.treeStore.append(None, [line, filename, 0])
        return it

    def _addResultLine (self, it, lineno, linetext):
        addTruncationMarker = False
        if len(linetext) > 1000:
            linetext = linetext[:1000]
            addTruncationMarker = True

        if not(self.query.isRegExp):
            (linetext, numLineMatches) = escapeAndHighlight(linetext, self.query.text, self.query.caseSensitive, self.query.wholeWord)
            self.numMatches += numLineMatches
        else:
            linetext = escapeMarkup(linetext)
            self.numMatches += 1
        self.numLines += 1

        if addTruncationMarker:
            linetext += "</span><span size=\"smaller\"><i> [...]</i>"
        line = "<b>%d:</b> <span foreground=\"blue\">%s</span>" % (lineno, linetext)
        self.treeStore.append(it, [line, None, lineno])

    def on_row_activated (self, widget, path, col):
        selectedIter = self.treeStore.get_iter(path)
        parentIter = self.treeStore.iter_parent(selectedIter)
        lineno = 0
        if parentIter == None:
            file = self.treeStore.get_value(selectedIter, 1)
        else:
            file = self.treeStore.get_value(parentIter, 1)
            lineno = self.treeStore.get_value(selectedIter, 2)

        if not(file):
            return

        uri="file://%s" % urllib.quote(file)
        location=Gio.file_new_for_uri(uri)
        Gedit.commands_load_location(self._window, location, None, lineno, -1)

        # use an Idle handler so the document has time to load:  
        GObject.idle_add(self.onDocumentOpenedCb)

    def on_btnClose_clicked (self, button):
        self.destroy()

    def destroy (self):
        if self.searchProcess:
            self.searchProcess.destroy()
            self.searchProcess = None

        panel = self._window.get_bottom_panel()
        resultContainer = self.builder.get_object('hbxFileSearchResult')
        resultContainer.set_data("filesearcher", None)
        panel.remove_item(resultContainer)
        self.treeStore = None
        self.treeView = None
        self._window = None
        self.files = {}
        self.builder = None
        self.pluginHelper.unregisterSearcher(self)

    def on_btnModify_clicked (self, button):
        if not(self.searchProcess):
            # edit search params
            pass
        else:
            # cancel search
            self.searchProcess.cancel()
            self.wasCancelled = True

    def on_tvFileSearchResult_button_press_event (self, treeview, event):
        if event.button == 3:
            path = treeview.get_path_at_pos(int(event.x), int(event.y))
            if path != None:
                treeview.grab_focus()
                treeview.set_cursor(path[0], path[1], False)

                menu = Gtk.Menu()
                self.contextMenu = menu # need to keep a reference to the menu
                mi = Gtk.ImageMenuItem.new_from_stock("gtk-copy", None)
                mi.connect_object("activate", FileSearcher.onCopyActivate, self, treeview, path[0])
                mi.show()
                menu.append(mi)

                mi = Gtk.SeparatorMenuItem.new()
                mi.show()
                menu.append(mi)

                mi = Gtk.MenuItem(_("Expand All"))
                mi.connect_object("activate", FileSearcher.onExpandAllActivate, self, treeview)
                mi.show()
                menu.append(mi)

                mi = Gtk.MenuItem(_("Collapse All"))
                mi.connect_object("activate", FileSearcher.onCollapseAllActivate, self, treeview)
                mi.show()
                menu.append(mi)

                menu.popup(None, None, None, None, event.button, event.time)
                return True
        else:
            return False

    def onCopyActivate (self, treeview, path):
        it = treeview.get_model().get_iter(path)
        markupText = treeview.get_model().get_value(it, 0)
        plainText = Pango.parse_markup(markupText, -1, u'\x00')[2]

        clipboard = Gtk.Clipboard.get(Gdk.SELECTION_CLIPBOARD)
        clipboard.set_text(plainText, -1)
        clipboard.store()

    def onExpandAllActivate (self, treeview):
        self._collapseAll = False
        treeview.expand_all()

    def onCollapseAllActivate (self, treeview):
        self._collapseAll = True
        treeview.collapse_all()

    def onDocumentOpenedCb (self):
        self._window.get_active_view().grab_focus()
        currDoc = self._window.get_active_document()

        # highlight matches in opened document:
        flags = 0
        if self.query.caseSensitive:
            flags |= 4
        if self.query.wholeWord:
            flags |= 2

        currDoc.set_search_text(self.query.text, flags)
        return False


def resultSearchCb (model, column, key, it, userdata):
    """Callback function for searching in result list"""
    lineText = model.get_value(it, column)
    plainText = Pango.parse_markup(lineText, -1, u'\x00')[2] # remove Pango markup

    # for file names, add a leading slash before matching:
    parentIter = model.iter_parent(it)
    if parentIter == None and not(plainText.startswith("/")):
        plainText = "/" + plainText

    # if search text contains only lower-case characters, do case-insensitive matching:
    if key.islower():
        plainText = plainText.lower()

    # if the line contains the search text, it matches:
    if plainText.find(key) >= 0:
        return False

    # line doesn't match:
    return True


def escapeMarkup (origText):
    "Replaces Pango markup special characters with their escaped replacements"
    text = origText
    text = text.replace('&', '&amp;')
    text = text.replace('<', '&lt;')
    text = text.replace('>', '&gt;')
    return text

def escapeAndHighlight (origText, searchText, caseSensitive, wholeWord):
    """
    Replaces Pango markup special characters, and adds highlighting markup
    around text fragments that match searchText.
    """

    # split origText by searchText; the resulting list will contain normal text
    # and matching text interleaved (if two matches are adjacent in origText,
    # they will be separated by an empty string in the resulting list).
    matchLen = len(searchText)
    fragments = []
    startPos = 0
    text = origText[:]
    pattern = buildQueryRE(searchText, caseSensitive, wholeWord)
    while True:
        m = pattern.search(text, startPos)
        if m is None:
            break
        pos = m.start()

        preStr = origText[startPos:pos]
        matchStr = origText[pos:pos+matchLen]
        fragments.append(preStr)
        fragments.append(matchStr)
        startPos = pos+matchLen
    fragments.append(text[startPos:])

    numMatches = (len(fragments) - 1) / 2

    if len(fragments) < 3:
        print "too few fragments (got only %d)" % len(fragments)
        print "text: '%s'" % origText.encode("utf8", "replace")
        numMatches += 1
    #assert(len(fragments) > 2)

    # join fragments again, adding markup around matches:
    retText = ""
    highLight = False
    for f in fragments:
        f = escapeMarkup(f)
        if highLight:
            retText += "<span background=\"#FFFF00\">%s</span>" % f
        else:
            retText += f
        highLight = not(highLight)
    return (retText, numMatches)
