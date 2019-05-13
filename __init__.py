from ts3plugin import ts3plugin
import ts3defines, os.path
import ts3lib as ts3
from ts3lib import getPluginPath
from os import path
from PythonQt.QtCore import Qt
from PythonQt.QtSql import QSqlDatabase
from PythonQt.QtGui import *
from pytsonui import *
from ts3widgets.serverview import ServerviewModel
            
class ContactManager(ts3plugin):
    # --------------------------------------------
    # Plugin info vars
    # --------------------------------------------

    name            = "Contact Manager"
    requestAutoload = False
    version         = "1.0"
    apiVersion      = 21
    author          = "Luemmel"
    description     = "Automatically grants talkpower, assigns channelgroups for blocked users or friends and kicks blocked users."
    offersConfigure = True
    commandKeyword  = ""
    infoTitle       = None
    hotkeys         = []
    menuItems       = [(ts3defines.PluginMenuType.PLUGIN_MENU_TYPE_GLOBAL, 0, "Contact Manager Settings", "")]
    directory       = path.join(getPluginPath(), "pyTSon", "scripts", "contactmanager")

    # --------------------------------------------
    # Custom error codes
    # --------------------------------------------

    error_setClientTalkpower    = ts3.createReturnCode()
    error_setClientChannelGroup = ts3.createReturnCode()
    error_kickFromChannel       = ts3.createReturnCode()

    # --------------------------------------------
    # Temporary vars
    # --------------------------------------------

    channel_group_list      = []
    channel_group_list_name = []
    dlg                     = None

    # --------------------------------------------
    # Settings
    # --------------------------------------------

    s_friends_chg   = None
    s_friends_tp    = None
    s_blocked_chg   = None
    s_blocked_kick  = None

    # --------------------------------------------
    # Debug
    # --------------------------------------------

    debug = False
    
    def onClientDisplayNameChanged(self, schid, clientID, displayName, uniqueClientIdentifier):
        
        # Own client ID and own channel
        (error, myid) = ts3.getClientID(schid)
        (error, mych) = ts3.getChannelOfClient(schid, myid)
        (error, cch) = ts3.getChannelOfClient(schid, clientID)
        
        status = self.contactStatus(uniqueClientIdentifier)

        
        # Only react if friend or blocked joined the channel
        if (status == 0 or status == 1) and mych == cch:

                # blocked
                if status == 1:

                    # Assign blocked channelgroup
                    if self.s_blocked_chg:
                        self.setClientChannelGroup(schid, 1, clientID, mych)

                    # kick blocked
                    if self.s_blocked_kick:
                        ts3.requestClientKickFromChannel(schid, clientID, "", self.error_kickFromChannel)

                # freinds
                if status == 0:

                    # Assign friends channelgroup
                    if self.s_friends_chg:
                        self.setClientChannelGroup(schid, 0, clientID, mych)

                    # Grant friends talkpower
                    if self.s_friends_tp:
                        ts3.requestClientSetIsTalker(schid, clientID, True, self.error_setClientTalkpower)

        

    def __init__(self):        
        # --------------------------------------------
        # Database
        # --------------------------------------------

        # Database connect for plugin main.db
        self.db = QSqlDatabase.addDatabase("QSQLITE", "pyTSon_contactmanager")
        self.db.setDatabaseName(path.join(self.directory, "main.db"))

        if not self.db.isValid(): raise Exception("Database main.db is invalid")
        if not self.db.open(): raise Exception("Could not open Database main.db")

        # Database connect for internal teamspeak settings.db
        self.db_c = QSqlDatabase.addDatabase("QSQLITE","pyTSon_contacts")
        self.db_c.setDatabaseName(ts3.getConfigPath() + "settings.db")

        if not self.db_c.isValid(): raise Exception("Database settings.db is invalid")
        if not self.db_c.open(): raise Exception("Could not open Database settings.db")

        # --------------------------------------------
        # Load General Settings
        # --------------------------------------------

        s = self.db.exec_("SELECT * FROM settings LIMIT 1")
        if not self.db.lastError().isValid():
            if self.debug: ts3.printMessageToCurrentTab("Settings SELECT succeeded!")
            if s.next():
                self.s_friends_chg = bool(s.value("s_friends_chg"))
                self.s_friends_tp = bool(s.value("s_friends_tp"))
                self.s_blocked_chg = bool(s.value("s_blocked_chg"))
                self.s_blocked_kick = bool(s.value("s_blocked_kick"))

    def stop(self):
        self.db.close()
        self.db.delete()
        self.db_c.close()
        self.db_c.delete()
        QSqlDatabase.removeDatabase("pyTSon_contactmanager")
        QSqlDatabase.removeDatabase("pyTSon_contacts")

    def configure(self, qParentWidget):
        self.openMainDialog()

    def onMenuItemEvent(self, sch_id, a_type, menu_item_id, selected_item_id):
        ts3.printMessageToCurrentTab(str())
        if a_type == ts3defines.PluginMenuType.PLUGIN_MENU_TYPE_GLOBAL:
            if menu_item_id == 0:
                self.openMainDialog()
    
    # Open mainwindow
    def openMainDialog(self):
        self.dlg = MainDialog(self)
        self.dlg.show()
        self.dlg.raise_()
        self.dlg.activateWindow()
                
    # This method fires on connect to a server and if you open the right system
    # Fires multipletimes for each channelgroup
    def onChannelGroupListEvent(self, schid, chgid, name, atype, iconID, saveDB):

        # If regular group
        if atype == 1:

            # Append channelgroup ids and channelgroup names to temporary vars
            self.channel_group_list.append(chgid)
            self.channel_group_list_name.append(name)
            if self.debug: ts3.printMessageToCurrentTab("CHGID: {0} CHNAME: {1}".format(chgid, name))

    # This method fires if all channelgroups were send via onChannelGroupListEvent()
    def onChannelGroupListFinishedEvent(self, schid):

        if self.debug: ts3.printMessageToCurrentTab("Channelgrouplist finished!")

        (error, sname) = ts3.getServerVariableAsString(schid, ts3defines.VirtualServerProperties.VIRTUALSERVER_NAME)
        (error, suid) = ts3.getServerVariableAsString(schid, ts3defines.VirtualServerProperties.VIRTUALSERVER_UNIQUE_IDENTIFIER)

        if self.debug: ts3.printMessageToCurrentTab("SUID: "+str(suid)+" CHANNELGROUPS: "+str(self.channel_group_list))

        # Start checking for channelgroup updates or if server is known
        self.checkServer(schid, sname, suid, self.channel_group_list, self.channel_group_list_name)

        # Reset temporary lists
        self.channel_group_list = []
        self.channel_group_list_name = []

    def checkServer(self, schid, sname, suid, channelgroups, channelgroups_name):
        s = self.db.exec_("SELECT * FROM server WHERE suid='"+str(suid)+"' LIMIT 1")
        if not self.db.lastError().isValid():
            # If server is known checkServerForUpdate() else insertServer()
            if s.next():
                if self.debug: ts3.printMessageToCurrentTab("Server known!")
                self.checkServerForUpdate(schid, sname, suid, channelgroups, channelgroups_name)
            else:
                if self.debug: ts3.printMessageToCurrentTab("Server unknown!")
                self.insertServer(schid, sname, suid, channelgroups, channelgroups_name)

    # This method inserts a new server into server table and channelgroups into channelgroups table
    def insertServer(self, schid, sname, suid, channelgroups, channelgroups_name):
        
        # Insert new Server in server table    
        i = self.db.exec_("INSERT INTO server (name, suid) VALUES ('%s', '%s')" % (sname,suid))
        if self.debug:
            if not self.db.lastError().isValid(): ts3.printMessageToCurrentTab("Server INSERT succeeded!")
            else: ts3.printMessageToCurrentTab("Server INSERT failed!!")

        # Get new Server DB id
        s = self.db.exec_("SELECT id FROM server WHERE suid='"+str(suid)+"' LIMIT 1")
        if not self.db.lastError().isValid():
            if s.next():
                sid = s.value("id")        
        
        # Insert channelgroups
        # Generating value string that goes into insert statemenet
        # sid - channelgroup id - channelgroup name
        channelgroup_insert_values = ""
        for index, val in enumerate(channelgroups):
            channelgroup_insert_values += "("+str(sid)+", '"+str(channelgroups[index])+"', '"+str(channelgroups_name[index])+"'),"
        # remove last char
        channelgroup_insert_values = channelgroup_insert_values[:-1] 

        # Insert all channelgroups + names
        i = self.db.exec_("INSERT INTO channelgroups (sid, chg, chg_name) VALUES "+channelgroup_insert_values)
        if self.debug:
            if not self.db.lastError().isValid(): ts3.printMessageToCurrentTab("Channelgroups INSERT succeeded!")
            else: ts3.printMessageToCurrentTab("Channelgroups INSERT failed!!")

    def checkServerForUpdate(self, schid, sname, suid, channelgroups, channelgroups_name):
        
        if self.debug: ts3.printMessageToCurrentTab("Start checking!")
        
        sid = None
        
        # Get Server DB id and name
        s = self.db.exec_("SELECT * FROM server WHERE suid='"+str(suid)+"' LIMIT 1")
        if not self.db.lastError().isValid():
            if self.debug: ts3.printMessageToCurrentTab("Server SELECT succeeded!")
            if s.next():
                sid = s.value("id")
                
                # If servername changed then update new servername
                if s.value("name") != sname:
                    u = self.db.exec_("UPDATE server SET name='%s' WHERE suid='%s' " % (sname,suid))
                    if self.debug:
                        if not self.db.lastError().isValid(): ts3.printMessageToCurrentTab("Name UPDATE succeeded!")
                        else: ts3.printMessageToCurrentTab("Name UPDATE failed!!")
        
        # Temporary vars for DB output
        check_channelgroups = []
        check_channelgroups_name = []
        
        s = self.db.exec_("SELECT chg, chg_name FROM channelgroups WHERE sid = "+str(sid))
        if not self.db.lastError().isValid():
            
            # Add all DB channelgroups to temporary vars
            while s.next():
                check_channelgroups.append(s.value("chg"))
                check_channelgroups_name.append(s.value("chg_name"))

       # If new channelgroups dont match db channelgroups then dump db data and insert new
        if check_channelgroups != channelgroups or check_channelgroups_name != channelgroups_name:
            
            
            # Delete all channelgroups from channelgroups table
            d = self.db.exec_("DELETE FROM channelgroups WHERE sid='"+str(sid)+"'")
            if self.debug:
                if not self.db.lastError().isValid(): ts3.printMessageToCurrentTab("Channelgroup DELETE succeeded!")
                else: ts3.printMessageToCurrentTab("Channelgroup DELETE failed!!")

            # Insert channelgroups
            # Generating value string that goes into insert statemenet
            # sid - channelgroup id - channelgroup name
            channelgroup_insert_values = ""
            for index, val in enumerate(check_channelgroups):
                channelgroup_insert_values += "("+str(sid)+", '"+str(check_channelgroups[index])+"', '"+str(check_channelgroups_name[index])+"'),"
            # remove last char
            channelgroup_insert_values = channelgroup_insert_values[:-1]

            # Insert all channelgroups + names
            i = self.db.exec_("INSERT INTO channelgroups (sid, chg, chg_name) VALUES %s" % (channelgroup_insert_values))
            if self.debug:
                if not self.db.lastError().isValid(): ts3.printMessageToCurrentTab("Channelgroups INSERT succeeded!")
                else: ts3.printMessageToCurrentTab("Channelgroups INSERT failed!!")

    def onClientMoveEvent(self, schid, clientID, oldChannelID, newChannelID, visibility, moveMessage):

        # Own client ID and own channel
        (error, myid) = ts3.getClientID(schid)
        (error, mych) = ts3.getChannelOfClient(schid, myid)

        # Only react if client joins my channel and at least one setting is activated
        if newChannelID == mych and not myid == clientID and (self.s_friends_chg or self.s_friends_tp or self.s_blocked_chg or self.s_blocked_kick or self.s_blocked_kick_option):

            # Contact status check
            (error, cuid) = ts3.getClientVariableAsString(schid, clientID, ts3defines.ClientProperties.CLIENT_UNIQUE_IDENTIFIER)
            status = self.contactStatus(cuid)

            # Only react if friend or blocked joined the channel
            if status == 0 or status == 1:

                    # blocked
                    if status == 1:

                        # Assign blocked channelgroup
                        if self.s_blocked_chg:
                            self.setClientChannelGroup(schid, 1, clientID, mych)

                        # kick blocked
                        if self.s_blocked_kick:
                            ts3.requestClientKickFromChannel(schid, clientID, "", self.error_kickFromChannel)

                    # freinds
                    if status == 0:

                        # Assign friends channelgroup
                        if self.s_friends_chg:
                            self.setClientChannelGroup(schid, 0, clientID, mych)

                        # Grant friends talkpower
                        if self.s_friends_tp:
                            ts3.requestClientSetIsTalker(schid, clientID, True, self.error_setClientTalkpower)

    def contactStatus(self, uid):
        # --------------------------------------------
        # Returns:
        # 2 = Normal user
        # 1 = Blocked user
        # 0 = Friend
        # --------------------------------------------
        status = 2
        s = self.db_c.exec_("SELECT * FROM contacts WHERE value LIKE '%%IDS="+str(uid)+"%%' LIMIT 1")
        if not self.db.lastError().isValid():
            if self.debug: ts3.printMessageToCurrentTab("Contact SELECT succeeded!")
            if s.next():
                val = s.value("value")
                for l in val.split('\n'):
                    if l.startswith('Friend='):
                        status = int(l[-1])
        return status
    
    def setClientChannelGroup(self, schid, status, cid, chid):
        
        (error, suid) = ts3.getServerVariableAsString(schid, ts3defines.VirtualServerProperties.VIRTUALSERVER_UNIQUE_IDENTIFIER)

        s = self.db.exec_("SELECT operatorgroup, banngroup FROM server WHERE suid='%s' LIMIT 1" % suid)
        if not self.db.lastError().isValid():
            if self.debug: ts3.printMessageToCurrentTab("OperatorGroup banngroup SELECT succeeded!")
            if s.next():
                (error, cdbid) = ts3.getClientVariableAsUInt64(schid, cid, ts3defines.ClientPropertiesRare.CLIENT_DATABASE_ID)
                group = None
                if status == 1: group = s.value("banngroup")
                if status == 0: group = s.value("operatorgroup")

                ts3.requestSetClientChannelGroup(schid, [group], [chid], [cdbid], self.error_setClientChannelGroup)

                
    # Catching Plguin Errors
    def onServerErrorEvent(self, schid, errorMessage, error, returnCode, extraMessage):
        if returnCode == self.error_kickFromChannel or returnCode == self.error_setClientTalkpower or returnCode == self.error_setClientChannelGroup: return True
    def onServerPermissionErrorEvent(self, schid, errorMessage, error, returnCode, failedPermissionID):
        if returnCode == self.error_kickFromChannel or returnCode == self.error_setClientTalkpower or returnCode == self.error_setClientChannelGroup: return True

class MainDialog(QDialog):
    try:
        def __init__(self, contactmanager, parent=None):
            try:                
                # shorten main object to cm
                self.cm = contactmanager
                
                super(QDialog, self).__init__(parent)
                setupUi(self, os.path.join(getPluginPath(), "pyTSon", "scripts", "contactmanager", "main.ui"))
                self.setWindowIcon(QIcon(os.path.join(getPluginPath(), "pyTSon", "scripts", "contactmanager", "icon.png")))
                self.setWindowTitle("Contact Manager")
                
                # Delete QDialog on Close
                self.setAttribute(Qt.WA_DeleteOnClose)
                
                # Disable help button
                self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint)
                
                # Load version from plguin vars
                self.label_version.setText("v"+self.cm.version)                
                
                # Button connects
                self.btn_anwenden.clicked.connect(self.save_changes)
                self.btn_anwenden_server.clicked.connect(self.save_changes_server)
                
                # Server QCombobox connect
                self.combo_servers.currentIndexChanged.connect(self.selectionchange)
                
                # Load checkboxes from plguin settings vars
                self.cb_friends_chg.setChecked(self.cm.s_friends_chg)
                self.cb_friends_tp.setChecked(self.cm.s_friends_tp)
                self.cb_blocked_chg.setChecked(self.cm.s_blocked_chg)
                self.cb_blocked_kick.setChecked(self.cm.s_blocked_kick)
                
                # Reserve space for MessageDialog
                msgdlg = None
                
                # Add servers to combo_servers with text= name and data= database id
                self.combo_servers.clear()
                s = self.cm.db.exec_("SELECT id, name FROM server")
                if not self.cm.db.lastError().isValid():
                    self.combo_servers.addItem("Select a server!", None)
                    while s.next():
                        self.combo_servers.addItem(s.value("name"), s.value("id"))    
                
            except:
                try:
                    from traceback import format_exc; ts3.logMessage(format_exc(), ts3defines.LogLevel.LogLevel_ERROR, "PyTSon Script", 0)
                except:
                    try:
                         from traceback import format_exc; print(format_exc())
                    except:
                        print("Unknown Error")

        def selectionchange(self, index):
        
            # If no server selected then reset combo_friends_channelgroup and combo_block_channelgroup
            if index == 0:
                self.combo_friends_channelgroup.clear()
                self.combo_block_channelgroup.clear()
                
            # Else (re)load combo_friends_channelgroup and combo_block_channelgroup
            else:
                # Get Data (server db id) from new combo_servers index
                id = self.combo_servers.itemData(index)
                self.loadChannelgroups(self.combo_friends_channelgroup, id)
                self.loadChannelgroups(self.combo_block_channelgroup, id)

        def loadChannelgroups(self, combobox, id):
        
            combobox.clear()
            s = self.cm.db.exec_("SELECT chg, chg_name FROM channelgroups WHERE sid ='"+str(id)+"'")
            if not self.cm.db.lastError().isValid():
                
                # Add "No channelgroup" item at beginning and set custom colors
                combobox.addItem("No channelgroup", None)
                combobox.setItemData(0, QColor("#515050"), Qt.BackgroundColorRole)
                combobox.setItemData(0, QColor("#ffffff"), Qt.TextColorRole)
                
                # Then add channelgroups to combo with text= chg name and data= chg id
                while s.next():
                    combobox.addItem(s.value("chg_name"), s.value("chg"))
            
            # Highlight channelgroups if they are already set in DB
            if combobox == self.combo_friends_channelgroup:
                s = self.cm.db.exec_("SELECT operatorgroup AS chg FROM server WHERE id="+str(id))
            else:
                s = self.cm.db.exec_("SELECT banngroup AS chg FROM server WHERE id="+str(id))
            if not self.cm.db.lastError().isValid():
                if s.next():
                
                    # If no channelgroup was set, then set combo index to 0
                    if s.value("chg") == "":
                        combobox.setCurrentIndex(0)
                    
                    # Else find chg id in combo data, restyle it and set current index this position
                    else:
                        index = combobox.findData(s.value("chg"))
                        combobox.setItemData(index, QColor("#ff9900"), Qt.BackgroundColorRole)
                        combobox.setItemData(index, QFont('MS Shell Dlg 2', 8, QFont.Bold), Qt.FontRole)
                        combobox.setCurrentIndex(index)

        def save_changes_server(self):
        
            # Get current server db id, friends and blocked chg id from current selections
            server = self.combo_servers.currentData
            freind = self.combo_friends_channelgroup.currentData
            block = self.combo_block_channelgroup.currentData
            
            # Set to NULL if "No channelgroup" was selected
            if freind == None: freind = "NULL"
            if block == None: block = "NULL"

            u = self.cm.db.exec_("UPDATE server SET operatorgroup="+str(freind)+", banngroup="+str(block)+" WHERE id="+str(server))
            if not self.cm.db.lastError().isValid():
                
                # Show success dialog
                self.msgdlg = MessageDialog(self)
                self.msgdlg.show()
                self.msgdlg.raise_()
                self.msgdlg.activateWindow()
                
                if self.cm.debug: ts3.printMessageToCurrentTab("Server Channelgruppen UPDATE succeeded!")

                # Reload combo_friends_channelgroup and combo_block_channelgroup
                # to renew the highlighted channelgroups
                self.loadChannelgroups(self.combo_friends_channelgroup, server)
                self.loadChannelgroups(self.combo_block_channelgroup, server)
            else:
                if self.cm.debug: ts3.printMessageToCurrentTab("Server Channelgruppen UPDATE failed!!")

        def save_changes(self):
            
            # Save current selection to plugin setting vars
            self.cm.s_friends_chg = self.cb_friend_o.isChecked()
            self.cm.s_friends_tp = self.cb_friend_tp.isChecked()
            self.cm.s_blocked_chg = self.cb_block_cb.isChecked()
            self.cm.s_blocked_kick = self.cb_kick.isChecked()
            
            # Update DB from plugin settings vars
            self.cm.db.exec_("UPDATE settings SET s_friends_chg = "+str(int(self.cm.s_friends_chg))+", "
                             "s_friends_tp = "+str(int(self.cm.s_friends_tp))+", "
                             "s_blocked_chg = "+str(int(self.cm.s_blocked_chg))+", "
                             "s_blocked_kick = "+str(int(self.cm.s_blocked_kick)))
            if not self.cm.db.lastError().isValid():
                
                # Show success dialog
                self.msgdlg = MessageDialog(self)
                self.msgdlg.show()
                self.msgdlg.raise_()
                self.msgdlg.activateWindow()
                
                if self.cm.debug: ts3.printMessageToCurrentTab("Settings UPDATE succeeded!")
            else:
                if self.cm.debug: ts3.printMessageToCurrentTab("Settings UPDATE failed!!")
    except:
        try:
            from traceback import format_exc; ts3.logMessage(format_exc(), ts3defines.LogLevel.LogLevel_ERROR, "PyTSon Script", 0)
        except:
            try:
                from traceback import format_exc;  print(format_exc())
            except:
                print("Unknown Error")


class MessageDialog(QDialog):
    def __init__(self, parent):
        super(QDialog, self).__init__(parent)
        setupUi(self, os.path.join(getPluginPath(), "pyTSon", "scripts", "contactmanager", "info.ui"))
        self.setWindowIcon(QIcon(os.path.join(getPluginPath(), "pyTSon", "scripts", "contactmanager", "info.png")))
        self.setWindowTitle("Information")
        
        # Button connect
        self.btn_ok.clicked.connect(self.closeMessageDialog)
        
        # Disable help button
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint | Qt.WindowStaysOnTopHint)
        
        # Delete QDialog on Close
        self.setAttribute(Qt.WA_DeleteOnClose)

    def closeMessageDialog(self):
        self.close()
