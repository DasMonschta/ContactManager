from ts3plugin import ts3plugin
import ts3defines, os.path
import ts3lib as ts3
from ts3lib import getPluginPath
from os import path
from PythonQt.QtCore import Qt, QTimer
from PythonQt.QtSql import QSqlDatabase
from PythonQt.QtGui import *
from pytsonui import *

class ContactManager(ts3plugin):
    # --------------------------------------------
    # Plugin info vars
    # --------------------------------------------

    name            = "Contact Manager"
    requestAutoload = False
    version         = "1.1"
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
    error_sendMessage           = ts3.createReturnCode()

    # --------------------------------------------
    # Temporary vars
    # --------------------------------------------

    channel_group_list      = []
    channel_group_list_name = []
    dlg                     = None
    changesdlg              = None

    # --------------------------------------------
    # Settings
    # --------------------------------------------    
    
    settings = {}    
    settings["f_channelgroup"]      = None
    settings["f_talkpower"]         = None
    settings["f_message"]           = None
    settings["f_message_message"]   = ""
    settings["b_channelgroup"]      = None
    settings["b_kick"]              = None
    settings["b_kick_message"]      = ""
    settings["b_message"]           = None
    settings["b_message_message"]   = ""
    
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
            if s.next():
                self.settings["f_channelgroup"]     = bool(s.value("db_f_channelgroup"))
                self.settings["f_talkpower"]        = bool(s.value("db_f_talkpower"))
                self.settings["f_message"]          = bool(s.value("db_f_message"))
                self.settings["f_message_message"]  = s.value("db_f_message_message")
                self.settings["b_channelgroup"]     = bool(s.value("db_b_channelgroup"))
                self.settings["b_kick"]             = bool(s.value("db_b_kick"))
                self.settings["b_kick_message"]     = s.value("db_b_kick_message")
                self.settings["b_message"]          = bool(s.value("db_b_message"))
                self.settings["b_message_message"]  = s.value("db_b_message_message")
                
                    
    def stop(self):
        self.db.close()
        self.db.delete()
        self.db_c.close()
        self.db_c.delete()
        QSqlDatabase.removeDatabase("pyTSon_contactmanager")
        QSqlDatabase.removeDatabase("pyTSon_contacts")        
        
    # --------------------------------------------
    # Dialog
    # --------------------------------------------   
    
    def configure(self, qParentWidget):
        self.openMainDialog()
        
    def onMenuItemEvent(self, sch_id, a_type, menu_item_id, selected_item_id):
        if a_type == ts3defines.PluginMenuType.PLUGIN_MENU_TYPE_GLOBAL:
            if menu_item_id == 0: self.openMainDialog()   
            
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

    # This method fires if all channelgroups were send via onChannelGroupListEvent()
    def onChannelGroupListFinishedEvent(self, schid):
        (error, sname) = ts3.getServerVariableAsString(schid, ts3defines.VirtualServerProperties.VIRTUALSERVER_NAME)
        (error, suid) = ts3.getServerVariableAsString(schid, ts3defines.VirtualServerProperties.VIRTUALSERVER_UNIQUE_IDENTIFIER)

        # Start checking for channelgroup updates or if server is known
        self.checkServer(schid, sname, suid, self.channel_group_list, self.channel_group_list_name)

        # Reset temporary lists
        self.channel_group_list = []
        self.channel_group_list_name = []

    def checkServer(self, schid, sname, suid, channelgroups, channelgroups_name):
        s = self.db.exec_("SELECT * FROM server WHERE db_suid='"+str(suid)+"' LIMIT 1")
        if not self.db.lastError().isValid():
            # If server is known checkServerForUpdate() else insertServer()
            if s.next(): self.checkServerForUpdate(schid, sname, suid, channelgroups, channelgroups_name)
            else: self.insertServer(schid, sname, suid, channelgroups, channelgroups_name)

    # This method inserts a new server into server table and channelgroups into channelgroups table
    def insertServer(self, schid, sname, suid, channelgroups, channelgroups_name):        
        # Insert new Server in server table    
        i = self.db.exec_("INSERT INTO server (db_name, db_suid) VALUES ('%s', '%s')" % (sname,suid))
        # Get new Server DB id
        s = self.db.exec_("SELECT db_id FROM server WHERE db_suid='"+str(suid)+"' LIMIT 1")
        if not self.db.lastError().isValid():
            if s.next(): sid = s.value("db_id")      
        
        # Insert channelgroups
        # Generating value string that goes into insert statemenet
        # sid - channelgroup id - channelgroup name
        channelgroup_insert_values = ""
        for index, val in enumerate(channelgroups):
            channelgroup_insert_values += "("+str(sid)+", '"+str(channelgroups[index])+"', '"+str(channelgroups_name[index])+"'),"
        # remove last char
        channelgroup_insert_values = channelgroup_insert_values[:-1] 

        # Insert all channelgroups + names
        i = self.db.exec_("INSERT INTO channelgroups (db_sid, db_id, db_name) VALUES "+channelgroup_insert_values)

    def checkServerForUpdate(self, schid, sname, suid, channelgroups, channelgroups_name):
        sid = None
        
        # Get Server DB id and name
        s = self.db.exec_("SELECT * FROM server WHERE db_suid='"+str(suid)+"' LIMIT 1")
        if not self.db.lastError().isValid():
            if s.next():             
                sid = s.value("db_id")
                
                # If servername changed then update new servername
                if s.value("db_name") != sname:
                    u = self.db.exec_("UPDATE server SET db_name='%s' WHERE db_suid='%s' " % (sname,suid))
        
        # Temporary vars for DB output
        check_channelgroups = []
        check_channelgroups_name = []
        
        s = self.db.exec_("SELECT db_id, db_name FROM channelgroups WHERE db_sid = "+str(sid))
        if not self.db.lastError().isValid():
            
            # Add all DB channelgroups to temporary vars
            while s.next():
                check_channelgroups.append(s.value("db_id"))
                check_channelgroups_name.append(s.value("db_name"))

       # If new channelgroups dont match db channelgroups then dump db data and insert new
        if check_channelgroups != channelgroups or check_channelgroups_name != channelgroups_name:
        
            # Delete all channelgroups from channelgroups table
            d = self.db.exec_("DELETE FROM channelgroups WHERE db_sid='"+str(sid)+"'")

            # Insert channelgroups
            # Generating value string that goes into insert statemenet
            # sid - channelgroup id - channelgroup name
            channelgroup_insert_values = ""
            for index, val in enumerate(channelgroups):
                channelgroup_insert_values += "("+str(sid)+", '"+str(channelgroups[index])+"', '"+str(channelgroups_name[index])+"'),"
            # remove last char
            channelgroup_insert_values = channelgroup_insert_values[:-1]
            ts3.printMessageToCurrentTab(channelgroup_insert_values)
            # Insert all channelgroups + names
            i = self.db.exec_("INSERT INTO channelgroups (db_sid, db_id, db_name) VALUES %s" % (channelgroup_insert_values))

            # Show Changes dialog
            self.changesdlg = ChangesDialog(self)
            self.changesdlg.show()
            self.changesdlg.raise_()
            self.changesdlg.activateWindow()

    def onClientMoveEvent(self, schid, clientID, oldChannelID, newChannelID, visibility, moveMessage):
        self.doContactActions(schid, clientID) 

    def onClientDisplayNameChanged(self, schid, clientID, displayName, uid):        
        QTimer.singleShot(200, lambda : self.doContactActions(schid, clientID))        
 
    def doContactActions(self, schid, clientID):    
        # Own client ID and own channel
        (error, myid) = ts3.getClientID(schid)
        (error, mych) = ts3.getChannelOfClient(schid, myid)
        (error, cch) = ts3.getChannelOfClient(schid, clientID)

        # Only react if client joins my channel and at least one setting is activated
        if cch == mych and not myid == clientID and (self.settings["f_channelgroup"] or self.settings["f_talkpower"] or self.settings["b_channelgroup"] or self.settings["b_kick"]):
            
            # Contact status check
            (error, cuid) = ts3.getClientVariableAsString(schid, clientID, ts3defines.ClientProperties.CLIENT_UNIQUE_IDENTIFIER)
            status = self.contactStatus(cuid)

            # Only react if friend or blocked joined the channel
            if status == 0 or status == 1:            
                # blocked
                if status == 1:
                    # Send message to blocked user
                    if self.settings["b_message"]:
                        ts3.requestSendPrivateTextMsg(schid, self.settings["b_message_message"], clientID, self.error_sendMessage)
                    # Assign blocked channelgroup
                    if self.settings["b_channelgroup"]:
                        self.setClientChannelGroup(schid, 1, clientID, mych)
                    # kick blocked
                    if self.settings["b_kick"]:
                        ts3.requestClientKickFromChannel(schid, clientID, self.settings["b_kick_message"], self.error_kickFromChannel)
                # freinds
                if status == 0:                
                    # Send message to blocked user
                    if self.settings["f_message"]:
                        ts3.requestSendPrivateTextMsg(schid, self.settings["f_message_message"], clientID, self.error_sendMessage)
                    # Assign friends channelgroup
                    if self.settings["f_channelgroup"]:
                        self.setClientChannelGroup(schid, 0, clientID, mych)
                    # Grant friends talkpower
                    if self.settings["f_talkpower"]:
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
            if s.next():
                val = s.value("value")
                for l in val.split('\n'):
                    if l.startswith('Friend='):
                        status = int(l[-1])
        return status
    
    def setClientChannelGroup(self, schid, status, cid, chid):        
        (error, suid) = ts3.getServerVariableAsString(schid, ts3defines.VirtualServerProperties.VIRTUALSERVER_UNIQUE_IDENTIFIER)

        db = self.db.exec_("SELECT db_f_channelgroup, db_b_channelgroup FROM server WHERE db_suid='"+str(suid)+"' LIMIT 1")
        if not self.db.lastError().isValid():
            if db.next():
                ts3.printMessageToCurrentTab(str(db.value("db_b_channelgroup")))
                if db.value("db_b_channelgroup") == "":
                    return
                (error, cdbid) = ts3.getClientVariableAsUInt64(schid, cid, ts3defines.ClientPropertiesRare.CLIENT_DATABASE_ID)
                group = None
                if status == 1: group = db.value("db_b_channelgroup")
                if status == 0: group = db.value("db_f_channelgroup")

                ts3.requestSetClientChannelGroup(schid, [group], [chid], [cdbid], self.error_setClientChannelGroup)
 
    # Catching Plguin Errors
    def onServerErrorEvent(self, schid, errorMessage, error, returnCode, extraMessage):
        if returnCode == self.error_sendMessage or returnCode == self.error_kickFromChannel or returnCode == self.error_setClientTalkpower or returnCode == self.error_setClientChannelGroup: return True
    
    def onServerPermissionErrorEvent(self, schid, errorMessage, error, returnCode, failedPermissionID):
        if returnCode == self.error_sendMessage or returnCode == self.error_kickFromChannel or returnCode == self.error_setClientTalkpower or returnCode == self.error_setClientChannelGroup: return True

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
                self.ui_label_version.setText("v"+self.cm.version)                
                
                # Button connects
                self.ui_btn_save.clicked.connect(self.save)
                
                # Server QCombobox connect
                self.ui_combo_server.currentIndexChanged.connect(self.serverSelectionChanged)
                
                # Load checkboxes from plguin settings vars
                self.ui_cb_f_channelgroup.setChecked(self.cm.settings["f_channelgroup"])
                self.ui_cb_f_talkpower.setChecked(self.cm.settings["f_talkpower"])
                self.ui_cb_b_channelgroup.setChecked(self.cm.settings["b_channelgroup"])
                self.ui_cb_b_kick.setChecked(self.cm.settings["b_kick"])     
                
                self.ui_cb_f_message.setChecked(self.cm.settings["f_message"])
                self.ui_cb_b_message.setChecked(self.cm.settings["b_message"])
                
                self.ui_line_b_kick_message.setText(self.cm.settings["b_kick_message"])
                self.ui_line_b_kick_message.setCursorPosition(0)
                
                self.ui_line_b_message.setText(self.cm.settings["b_message_message"])
                self.ui_line_b_message.setCursorPosition(0)
                
                self.ui_line_f_message.setText(self.cm.settings["f_message_message"])
                self.ui_line_f_message.setCursorPosition(0)
                
                # Reserve space for MessageDialog
                msgdlg = None
                
                # Add servers to ui_combo_server with text= name and data= database id
                self.ui_combo_server.clear()
                s = self.cm.db.exec_("SELECT db_id, db_name FROM server")
                if not self.cm.db.lastError().isValid():
                    self.ui_combo_server.addItem("Select a server!", None)
                    while s.next():
                        self.ui_combo_server.addItem(s.value("db_name"), s.value("db_id"))    
                
            except:
                try:
                    from traceback import format_exc; ts3.logMessage(format_exc(), ts3defines.LogLevel.LogLevel_ERROR, "PyTSon Script", 0)
                except:
                    try:
                         from traceback import format_exc; print(format_exc())
                    except:
                        print("Unknown Error")

        def serverSelectionChanged(self, index):            
            # If no server selected then reset ui_combo_f_channelgroup and ui_combo_b_channelgroup
            if index == 0:
                self.ui_combo_f_channelgroup.clear()
                self.ui_combo_b_channelgroup.clear()
                
            # Else (re)load ui_combo_f_channelgroup and ui_combo_b_channelgroup
            else:
                # Get Data (server db id) from new combo_servers index
                id = self.ui_combo_server.itemData(index)
                self.loadChannelgroups(self.ui_combo_f_channelgroup, id)
                self.loadChannelgroups(self.ui_combo_b_channelgroup, id)

        def loadChannelgroups(self, combobox, id):            
            combobox.clear()
            s = self.cm.db.exec_("SELECT db_id, db_name FROM channelgroups WHERE db_sid ='"+str(id)+"'")
            if not self.cm.db.lastError().isValid():                
                # Add "No channelgroup" item at beginning and set custom colors
                combobox.addItem("No channelgroup", None)
                combobox.setItemData(0, QColor("#515050"), Qt.BackgroundColorRole)
                combobox.setItemData(0, QColor("#ffffff"), Qt.TextColorRole)
                
                # Then add channelgroups to combo with text= db_name name and data= db_id
                while s.next():
                    combobox.addItem(s.value("db_name"), s.value("db_id"))
            
            # Highlight channelgroups if they are already set in DB
            if combobox == self.ui_combo_f_channelgroup:
                s = self.cm.db.exec_("SELECT db_f_channelgroup AS db_channelgroup FROM server WHERE db_id="+str(id))
            else:
                s = self.cm.db.exec_("SELECT db_b_channelgroup AS db_channelgroup FROM server WHERE db_id="+str(id))
            if not self.cm.db.lastError().isValid():
                if s.next():                
                    # If no channelgroup was set, then set combo index to 0
                    if s.value("db_channelgroup") == "":
                        combobox.setCurrentIndex(0)
                    
                    # Else find chg id in combo data, restyle it and set current index this position
                    else:
                        index = combobox.findData(s.value("db_channelgroup"))
                        combobox.setItemData(index, QColor("#ff9900"), Qt.BackgroundColorRole)
                        combobox.setItemData(index, QFont('MS Shell Dlg 2', 8, QFont.Bold), Qt.FontRole)
                        combobox.setCurrentIndex(index)

        def save(self):        
            # Get current server db id, friends and blocked chg id from current selections
            current_server = self.ui_combo_server.currentData
            current_f_channelgroup = self.ui_combo_f_channelgroup.currentData
            current_b_channelgroup = self.ui_combo_b_channelgroup.currentData
            
            # Set to NULL if "No channelgroup" was selected
            if current_f_channelgroup == None: current_f_channelgroup = "NULL"
            if current_b_channelgroup == None: current_b_channelgroup = "NULL"

            u = self.cm.db.exec_("UPDATE server SET db_f_channelgroup="+str(current_f_channelgroup)+", db_b_channelgroup="+str(current_b_channelgroup)+" WHERE db_id="+str(current_server))
            if not self.cm.db.lastError().isValid():   
                # Reload combo_friends_channelgroup and combo_block_channelgroup
                # to renew the highlighted channelgroups
                self.loadChannelgroups(self.ui_combo_f_channelgroup, current_server)
                self.loadChannelgroups(self.ui_combo_b_channelgroup, current_server)
                
            ts3.printMessageToCurrentTab("so far so goood")
            
            # Save current selection to plugin setting vars
            self.cm.settings["f_channelgroup"] = self.ui_cb_f_channelgroup.isChecked()
            self.cm.settings["f_talkpower"] = self.ui_cb_f_talkpower.isChecked()
            self.cm.settings["f_message"] = self.ui_cb_f_message.isChecked()
            self.cm.settings["f_message_message"] = self.ui_line_f_message.text.replace('"', '').replace("'", "")
            self.cm.settings["b_channelgroup"] = self.ui_cb_b_channelgroup.isChecked()
            self.cm.settings["b_kick"] = self.ui_cb_b_kick.isChecked() 
            self.cm.settings["b_kick_message"] = self.ui_line_b_kick_message.text.replace('"', '').replace("'", "")
            self.cm.settings["b_message"] = self.ui_cb_b_message.isChecked()
            self.cm.settings["b_message_message"] = self.ui_line_b_message.text.replace('"', '').replace("'", "")
    
            self.ui_line_b_kick_message.setText(self.cm.settings["b_kick_message"])
            self.ui_line_b_kick_message.setCursorPosition(0)

            self.ui_line_b_message.setText(self.cm.settings["b_message_message"])
            self.ui_line_b_message.setCursorPosition(0)

            self.ui_line_f_message.setText(self.cm.settings["f_message_message"])
            self.ui_line_f_message.setCursorPosition(0)
            
            # Update DB from plugin settings vars
            self.cm.db.exec_("UPDATE settings SET db_f_channelgroup = "+str(int(self.cm.settings["f_channelgroup"]))+", "
                             "db_f_talkpower = "+str(int(self.cm.settings["f_talkpower"]))+", "
                             "db_f_message = "+str(int(self.cm.settings["f_message"]))+", "
                             "db_f_message_message = '"+self.cm.settings["f_message_message"]+"', "
                             "db_b_channelgroup = "+str(int(self.cm.settings["b_channelgroup"]))+", "
                             "db_b_kick = "+str(int(self.cm.settings["b_kick"]))+", "
                             "db_b_kick_message = '"+self.cm.settings["b_kick_message"]+"', "
                             "db_b_message = "+str(int(self.cm.settings["b_message"]))+", "
                             "db_b_message_message = '"+self.cm.settings["b_message_message"]+"'")
                             
            if not self.cm.db.lastError().isValid():
                # Show success dialog
                self.msgdlg = MessageDialog(self)
                self.msgdlg.show()
                self.msgdlg.raise_()
                self.msgdlg.activateWindow()

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
        self.setWindowIcon(QIcon(os.path.join(getPluginPath(), "pyTSon", "scripts", "contactmanager", "icon.png")))
        self.setWindowTitle("That was easy!")
        
        # Button connect
        self.ui_btn_ok.clicked.connect(self.closeMessageDialog)
        
        # Disable help button
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint | Qt.WindowStaysOnTopHint)
        
        # Delete QDialog on Close
        self.setAttribute(Qt.WA_DeleteOnClose)

    def closeMessageDialog(self):
        self.close()       
        
        
class ChangesDialog(QDialog):
    def __init__(self, contactmanager, parent=None):
        super(QDialog, self).__init__(parent)
        setupUi(self, os.path.join(getPluginPath(), "pyTSon", "scripts", "contactmanager", "info_changes.ui"))
        self.setWindowIcon(QIcon(os.path.join(getPluginPath(), "pyTSon", "scripts", "contactmanager", "icon.png")))
        self.setWindowTitle("There are changes!")
        
        self.cm = contactmanager
        
        # Button connect
        self.ui_btn_ok.clicked.connect(self.closeMessageDialog)
        self.ui_btn_settings.clicked.connect(self.openSettings)
        
        # Disable help button
        self.setWindowFlags(self.windowFlags() & ~Qt.WindowContextHelpButtonHint | Qt.WindowStaysOnTopHint)
        
        # Delete QDialog on Close
        self.setAttribute(Qt.WA_DeleteOnClose)
        
    def openSettings(self):
        self.cm.openMainDialog()
        self.close()       

    def closeMessageDialog(self):
        self.close()