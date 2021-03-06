#!/bin/env python3

from urllib.request import urlopen, Request
from json import load, dump, loads
import subprocess
import tempfile
import re
import argparse
import os

namere = re.compile("""<td itemprop="name">(?P<name>[^<>]+)</td>""")
startinfore = re.compile("""<tr>[\n\s]*
                         <td>(?P<description>.*?)</td>[\n\s]*
                         <td>(?P<executable>[^<>]*)</td>[\n\s]*
                         <td>(?P<arguments>[^<>]*)</td>[\n\s]*
                         <td>(?P<type>.*?)</td>[\n\s]*
                         <td\ class="nowrap">[\n\s]*
                         (?P<os><i\ class="[^"]+"\ aria-label="Windows">[\n\s]*
                         </i>[\n\s]*)?
                         </td>[\n\s]*
                         <td>(?P<extra>[^<>]*)</td>[\n\s]*
                         </tr>""", re.X)

installdirre = re.compile("""<tr>[\n\s]*
                          <td>installdir</td>[\n\s]*
                          <td>(?P<installdir>[^<>]+)</td>[\n\s]*
                          </tr>[\n\s]*
                          """, re.X)

class LaunchInfo:
  def __init__(self, match_dict, install_dir):
    self.executable = install_dir + '/' + re.sub(r'\\', r'/', match_dict['executable'])
    if 'arguments' in match_dict:
      self.arguments = match_dict["arguments"]
    else:
      self.arguments = ""
    self.description = match_dict["description"]
  def __repr__(self):
    return "(LaunchInfo: {0} {1} # {2})".format(self.executable,
                                                self.arguments, self.description)

colonre = re.compile(r'^(\s*"[^"]+")', re.MULTILINE)
commare = re.compile(r'("|})(\s*$\s*")', re.MULTILINE)
def get_app_config(appid):
  result = subprocess.check_output(["steamcmd", "+app_info_print", str(appid),
                           "+quit"]).decode('utf-8')
  json_begin = re.search(colonre, result)
  if json_begin is None:
    print(result)
    raise
  json_begin = json_begin.start()
  steam_json = result[json_begin:]
  steam_json = re.sub(colonre, r'\1:', steam_json)
  steam_json = re.sub(commare, r'\1,\2', steam_json)
  appinfo = loads('{' + steam_json + '}')[str(appid)]
  appinfos = dict()
  appinfos['infos'] = dict()
  appinfos['id'] = appid
  installdir = appinfo['config']['installdir']
  appinfos['installdir'] = installdir
  appinfos['name'] = appinfo['common']['name']
  for k, v in appinfo['config']['launch'].items():
    if v['config']['oslist'] == 'windows':
      name = v['description']
      if name == "":
        name = appinfos['name']
      appinfos['infos'][name] = LaunchInfo(v, installdir)
  for k, v in appinfo['depots'].items():
    if not 'config' in v:
      continue
    if v['config']['oslist'] == 'windows':
      appinfos['depot'] = v
      appinfos['depot']['id'] = k
  return appinfos

def get_app_config_http(appid):
  configurl = "http://steamdb.info/app/" + str(appid) + "/config/"
  print(configurl)
  hdr = {'User-Agent': 'Mozilla/5.0 (X11; Linux x86_64)'}
  req = Request(configurl, headers = hdr)
  content = urlopen(req).read().decode('utf-8')
  startinfos = dict()
  startinfos["id"] = appid
  startinfos["infos"] = dict()
  startinfos["name"] = namere.search(content).groupdict()["name"]
  installdir = installdirre.search(content).groupdict()["installdir"]
  startinfos["installdir"] = installdir
  for startinfo_m in startinfore.finditer(content):
    match_dict = startinfo_m.groupdict()
    startinfo = LaunchInfo(match_dict, installdir)
    name = startinfo.description
    if '<' in name or name == "":
      name = startinfos["name"]
    startinfos["infos"][name] = startinfo
  return startinfos

def generate_manifest(appinfos):
  manifest = """
"AppState"
{
  "appid"               "%d"
  "Universe"            "1"
  "name"                "%s"
  "StateFlags"          "4"
  "installdir"          "%s"
  "AutoUpdateBehavior"  "1"
}
""" % (appinfos["id"], appinfos["name"], appinfos["installdir"])
  return manifest

def generate_runscript(appinfo: LaunchInfo, config):
  print("...for " + appinfo.executable)
  runscript = """
#!/bin/bash
export WINEPREFIX="{0}"
export WINEDLLPATH+=":{4}"
export LD_LIBRARY_PATH+=":{5}:{4}"
export WINEDEBUG="trace+steam_api"
export WINEARCH="win32"
export WINEDLLOVERRIDES="*steam_api=b"
export SteamAppId="{6}"
export SteamControllerAppId="{6}"
export SteamGameId="{6}"
export SteamUser="{7}"
export SteamAppUser="{7}"
LD_PRELOAD="gameoverlayrenderer.so" wine "{1}/common/{2}" {3} &> "$(dirname "$0")/lastrun.log"
""".format(config['wineprefix'], config['steamapps'], appinfo.executable,
           appinfo.arguments, config['dllpath'], config['overlaypath'],
           config['appid'], config['login'])
  return runscript

aparser = argparse.ArgumentParser(description="Steam windows game installation script")
aparser.add_argument('appid', type=int, help="appid of the game to be installed", metavar='appID')
aparser.add_argument('-w', '--wineprefix', help='path to wineprefix to be used to launch this app', type=str, dest='wineprefix', default=os.getenv('HOME') + '/.wine')

config = dict()
try:
  with open("steamforwarder.json", "r") as f:
    config = load(f)
except:
  print("Configuration file not found! Using default values... You may change them at steamforwarder.json")
  config['overlaypath'] = os.getenv("HOME") + "/.local/share/Steam/ubuntu12_32/"
  config['dllpath'] = os.getenv("PWD")
  steamfolder = os.getenv('HOME') + '/.local/share/Steam'
  print(steamfolder)
  if os.path.isdir(steamfolder):
    print("is dir")
    for d in os.listdir(steamfolder):
      print(d)
      if not re.match("[sS]team[aA]pps", d) is None:
        config['steamapps'] = steamfolder + '/' + d
  config['login'] = 'anonymous'
  with open("steamforwarder.json", "w") as f:
    dump(config, f, indent=2)
  if not 'steamapps' in config:
    config['steamapps'] = ""

aparser.add_argument('-l', '--login', help='your login at steam', type=str, dest='login', default=config['login'])
aparser.add_argument('-s', '--steamapps-dir', help='path to the steamapps dir', type=str, dest='steamapps', default=config["steamapps"])
aparser.add_argument('-d', '--dll-dir', help='path to the steam_api.dll.so and libsteam_api.so', type=str, dest='dllpath', default=config["dllpath"])
aparser.add_argument('-o', '--overlay-dir', help='path to the gameoverlayrenderer.so and other steam libs', type=str, dest='overlaypath', default=config["overlaypath"])
aparser.add_argument('-p', '--password', help='password of your steam account (may be necessary for non-free apps). Note: password will not be saved anywhere including configuration file', type=str, dest='password', default="")
aparser.add_argument('--store', help='save configuration for futher use as default', dest='store', default=False, action='store_true')
config_args = aparser.parse_args()
config['login'] = config_args.login
config['wineprefix'] = config_args.wineprefix
config['dllpath'] = config_args.dllpath
config['overlaypath'] = config_args.overlaypath
if config_args.steamapps == "":
  print('Can not find steam location... Please specify it using -s key')
  quit(1)
config['steamapps'] = config_args.steamapps
if config_args.store:
  with open("steamforwarder.json", "w") as f:
    dump(config, f, indent=2)
config['password'] = config_args.password
appid = config_args.appid
config['appid'] = appid
  
print("Obtaining app info...")
try:
  appinfos = get_app_config(appid)
except:
  print("Failed to get appinfo via steamcmd, falling back to http method...")
  appinfos = get_app_config_http(appid)
manifest = generate_manifest(appinfos)
manifest_location = config["steamapps"] + '/appmanifest_' + str(appid) + '.acf'
print("Generating manifest...")
with open(manifest_location, "w") as f:
  f.write(manifest)

rs_location = config["steamapps"] + '/common/' + appinfos["installdir"] + '/'
print("Downloading " + appinfos["name"] + " via steamcmd...")
steam_script = """
login {0} {1}
@sSteamCmdForcePlatformType windows
app_license_request {2}
app_update {2} validate
quit
""".format(config['login'], config['password'], str(appid))
# These scripts might be useful for future
#steam_depot_script = """
#login {0} {1}
#@sSteamCmdForcePlatformType windows
#force_install_dir "{4}"
#app_license_request {2}
#download_depot {2} {3}
#quit
#""".format(config['login'], config['password'], str(appid),
#           appinfos['depot']['id'], rs_location)
#steam_nocmd_script = """
#@sSteamCmdForcePlatformType windows
#app_license_request {0}
#download_depot {0} {1}
#""".format(str(appid), appinfos['depot']['id'])
with tempfile.NamedTemporaryFile('w') as f:
  f.write(steam_script)
  f.flush()
  subprocess.run(["steamcmd", "+runscript", f.name])
print("Generating runscripts...")
for name, appinfo in appinfos["infos"].items():
  runscript = generate_runscript(appinfo, config)
  runscript_location = (rs_location + name + '.sh')
  with open(runscript_location, "w") as f:
    f.write(runscript)
print("Placing steam_appid.txt to the game location...")
with open(rs_location + '/steam_appid.txt', "w") as f:
  f.write(str(appid))
print("Done! You may launch the game via scripts located at " + rs_location)

