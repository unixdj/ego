# -*- coding: ascii -*-

import os
import shlex
from subprocess import PIPE
from subprocess import Popen
from subprocess import STDOUT

from funtoo.boot.menu import BootLoaderMenu, BootLoaderEntryType, BootMenuFlag
from funtoo.boot.extension import Extension, ExtensionError
from funtoo.boot.config import BootConfigFile


def getExtension(boot_config, config, boot_options, ego_module):
	""" Gets the extension based on the configuration """
	return GRUBExtension(boot_config, config, boot_options, ego_module)


class GRUBExtension(Extension):
	""" Implements an extension for the grub bootloader """
	
	def __init__(self, boot_config: BootConfigFile, config, boot_options, ego_module, testing=False):
		super().__init__(boot_config, config, boot_options, ego_module)
		self.grubpath = "{path}/{dir}".format(path=self.boot_config["boot/path"], dir=self.boot_config["grub/dir"])
		# fn = path for output grub.cfg.
		self.fn = "{path}/{file}".format(path=self.grubpath, file=self.boot_config["grub/file"])
		if self.fn.startswith("/"):
			self.fn = self.fn[1:]
		self.fn = os.path.join(self.config.root_path, self.fn)
		self.bootitems = []
		self.testing = testing
		self.GuppyMap()
		self.defname = "undefined"

		if os.path.exists("/sys/firmware/efi"):
			self.uefiboot = True
		else:
			self.uefiboot = False
	
	def _attempt_kernel(self, boot_menu, set_default=False) -> bool:
		identifier = None
		
		if set_default is True:
			# set_default means "just set the default kernel to be the next attempted kernel" (to wipe any existing attempt)
			seek_flag = BootMenuFlag.DEFAULT
			# remove any remaining setting:
			self.boot_config.idmapper.remove_promote_setting()
		else:
			seek_flag = BootMenuFlag.ATTEMPT
		
		for item in boot_menu.boot_entries:
			if seek_flag in item["flags"]:
				identifier = item["pos"]
		if identifier is None:
			if set_default is False:
				self.msgs.append(["fatal", "Unable to find next-attempted kernel entry."])
			return False
		cmd = "/usr/sbin/grub-reboot"
		cmdobj = Popen([cmd, str(identifier)], bufsize=-1, stdout=PIPE, stderr=PIPE, shell=False)
		output = cmdobj.communicate()
		retval = cmdobj.poll()
		if retval != 0:
			if set_default is False:
				self.msgs.append(["fatal", "Unable to set next-attempted kernel to entry \"%s\"." % identifier])
			return False
		else:
			if set_default is False:
				self.msgs.append(["info", "Next-attempted kernel set to entry \"%s\"." % identifier])
			return True
	
	def _set_default(self, boot_menu) -> bool:
		identifier = None
		for item in boot_menu.boot_entries:
			if BootMenuFlag.DEFAULT in item["flags"]:
				identifier = item["pos"]
				label = item["label"]
		if identifier is None:
			self.msgs.append(["fatal", "Unable to find default kernel entry."])
			return False
		cmd = "/usr/sbin/grub-set-default"
		cmdobj = Popen([cmd, str(identifier)], bufsize=-1, stdout=PIPE, stderr=PIPE, shell=False)
		output = cmdobj.communicate()
		retval = cmdobj.poll()
		if retval != 0:
			self.msgs.append(["fatal", "Unable to set default kernel to %s." % label])
			return False
		else:
			self.msgs.append(["info", "Default kernel set to entry %s." % label])
			return True
	
	def grubProbe(self):
		gprobe = "/usr/sbin/grub-probe"
		if not os.path.exists(gprobe):
			gprobe = "/sbin/grub-probe"
		if not os.path.exists(gprobe):
			raise ExtensionError("couldn't find grub-probe")
		return gprobe
	
	def generateOtherBootEntry(self, boot_menu: BootLoaderMenu, sect) -> bool:
		""" Generates the boot entry for other systems """
		mytype = self.boot_config["{s}/type".format(s=sect)].lower()
		if mytype in ["dos", "msdos"]:
			mytype = "dos"
		elif mytype in ["windows", "windows 2000", "win2000", "windows xp", "winxp"]:
			mytype = "winxp"
		elif mytype in ["windows vista", "vista"]:
			mytype = "vista"
		elif mytype in ["windows 7", "win7"]:
			mytype = "win7"
		elif mytype in ["windows 8", "win8"]:
			mytype = "win8"
		elif mytype in ["windows 10", "win10"]:
			mytype = "win10"
		elif mytype in ["haiku", "haiku os"]:
			mytype = "haiku"
		elif mytype in ["linux16"]:
			mytype = "linux16"
		else:
			self.msgs.append(["fatal", "Unrecognized boot entry type \"{mt}\"".format(mt=mytype)])
			return False
		params = self.boot_config["{s}/params".format(s=sect)].split()
		myroot = self.resolver.GetParam(params, "root=")
		mychainloader = self.resolver.GetParam(params, "chainloader=")
		menuflags = self.boot_config["{s}/menuflags".format(s=sect)]
		myname = sect
		# TODO check for valid root entry
		boot_menu.lines.append("")
		boot_menu.lines.append("menuentry \"{mn}\" {mf} {{".format(mn=myname, mf=menuflags))
		if mytype in ["linux16"]:
			k = self.resolver.strip_mount_point(self.boot_config[sect + "/kernel"])
			full_k = os.path.join(self.boot_config["boot/path"], k.lstrip("/"))
			if not os.path.exists(full_k):
				self.msgs.append(["warn", "Image for section {sect} not found - {full_k}".format(sect=sect, full_k=full_k)])
			else:
				self.bootitems.append(myname)
				boot_menu.lines.append("  linux16 " + k)
		else:
			# TODO: add entry to boot_menu object
			self.PrepareGRUBForDevice(myroot, boot_menu.lines)
			self.bootitems.append(myname)
			self.DeviceGRUB(myroot)
			if mytype in ["win7", "win8"] or mytype == "win10" and self.uefiboot is False:
				boot_menu.lines.append("  chainloader " + mychainloader) if mychainloader else boot_menu.lines.append("  chainloader +4")
			elif mytype in ["vista", "dos", "winxp", "haiku"]:
				boot_menu.lines.append("  chainloader " + mychainloader) if mychainloader else boot_menu.lines.append("  chainloader +1")
			elif mytype in ["win10"]:
				boot_menu.lines.append("  chainloader " + mychainloader) if mychainloader else boot_menu.lines.append("  chainloader /EFI/Microsoft/Boot/bootmgfw.efi")
		boot_menu.lines.append("}")
		boot_menu.addBootEntry(BootLoaderEntryType.OTHER, label=myname)
		return True
	
	def generateBootEntry(self, boot_menu: BootLoaderMenu, sect: str, k_full_path: str, kext: str) -> bool:
		""" Generates the boot entry """
		mytype = self.boot_config["{s}/type".format(s=sect)]
		boot_menu.lines.append("")
		label = self.resolver.GetBootEntryString(sect, k_full_path)
		menuflags = self.boot_config["{s}/menuflags".format(s=sect)]
		boot_menu.lines.append("menuentry \"{l}\" {mf} {{".format(l=label, mf=menuflags))
		
		# TODO: add last-selected, which is different than last-booted.
		#if self.config["boot/autopick"] == "last-booted":
		#	boot_menu.lines.append("    savedefault")
		
		# self.bootitems records all our boot items
		self.bootitems.append(label)
		
		scanpath = os.path.join(self.config.root_path, self.boot_config.item(sect, "scan").lstrip("/"))
		
		self.PrepareGRUBForFilesystem(scanpath, boot_menu.lines)
		
		# removes ROOT env var and /boot from the kernel path:
		k_sub_path = self.resolver.strip_mount_point(k_full_path)
		c = self.boot_config
		params = []
		if c.hasItem("boot/terminal") and c["boot/terminal"] == "serial":
			params += [
				"console=tty0",
				"console=ttyS%s,%s%s%s" % (c["serial/unit"], c["serial/speed"], c["serial/parity"][0], c["serial/word"])
			]
		for param in self.boot_config["{s}/params".format(s=sect)].split():
			if param not in params:
				params.append(param)
		
		# Logic here to see if we are processing a boot entry that is a kernel we should "attempt" to boot. It gets special parameters added to its boot
		# entry. It may be tagged by the user on this call to ego boot (user_specified_attempt_identifier) or we may simply have boot_menu.attempt_kname
		# set due to an attempted kernel having been selected previously:

		entry = boot_menu.addBootEntry(BootLoaderEntryType.LINUX, label=label, image_path=k_full_path)
		if BootMenuFlag.ATTEMPT in entry["flags"]:
			# Add special boot parameters for a kernel we are attempting to boot (usually panic=10 or similar to force a reboot)
			for param in self.boot_config["{s}/attemptparams".format(s=sect)].split():
				if param not in params:
					params.append(param)
		
		# TODO: turn off panic setting after successful boot? (ego boot success?)
		
		ok, myroot = self.resolver.calculate_rootfs_for_section(params)
		if not ok:
			return False
		ok, fstype = self.resolver.calculate_filesystem_for_section(params)
		if not ok:
			return False
		
		initrds = self.boot_config.item(sect, "initrd")
		initrds = self.resolver.find_initrds(initrds, scanpath, k_full_path, kext)
		if myroot and ('root=' + myroot) in params and 0 == len(initrds):
			params.remove('root=' + myroot)
			params.append('root=' + self.resolver.resolvedev(myroot))
		
		xenpath = None
		xenparams = None
		
		# Populate xen variables if type is xen
		if mytype == "xen":
			xenkernel = self.boot_config["{s}/xenkernel".format(s=sect)]
			# Add leading / if needed
			if not xenkernel.startswith("/"):
				xenkernel = "/{xker}".format(xker=xenkernel)
			xenpath = self.resolver.strip_mount_point(xenkernel)
			xenparams = self.boot_config["{s}/xenparams".format(s=sect)].split()
		
		# Add unique identifier that can be used to determine if kernel booted.
		params.append("rand_id=%s" % self.resolver.idmapper.get(k_full_path))
		# Append kernel lines based on type
		if mytype == "xen":
			boot_menu.lines.append("  multiboot {xker} {xparams}".format(xker=xenpath, xparams=" ".join(xenparams)))
			boot_menu.lines.append("  module {ker} {params}".format(ker=k_sub_path, params=" ".join(params)))
			for initrd in initrds:
				boot_menu.lines.append("  module {initrd}".format(initrd=self.resolver.strip_mount_point(initrd)))
		else:
			boot_menu.lines.append("  {t} {k} {par}".format(t=mytype, k=k_sub_path, par=" ".join(params)))
			if initrds:
				initrds = (self.resolver.strip_mount_point(initrd) for initrd in initrds)
				boot_menu.lines.append("  initrd {rds}".format(rds=" ".join(initrds)))
		
		# Append graphics line
		if self.boot_config.hasItem("{s}/gfxmode".format(s=sect)):
			skipgfx = False
			for p in params:
				if p.startswith("vga=") or p.startswith("video=uvesafb:"):
					skipgfx = True
					break
			if not skipgfx:
				boot_menu.lines.append("  set gfxpayload=keep")
		boot_menu.lines.append("}")

		return ok
	
	def sanitizeDisplayMode(self, dm):
		if self.uefiboot and dm == "text":
			# UEFI doesn't support text mode:
			return "640x480"
		else:
			return dm
	
	def generateConfigFile(self, boot_menu: BootLoaderMenu):
		if self.uefiboot:
			self.msgs.append(["note", "Detected UEFI boot. Configuring for UEFI booting."])
		else:
			self.msgs.append(["note", "Detected MBR boot. Configuring for Legacy MBR booting."])
		boot_menu.lines.append(self.boot_config.condFormatSubItem("boot/timeout", "set timeout={s}"))
		# pass our boot entry generator function to GenerateSections,
		# and everything is taken care of for our boot entries
		
		boot_menu.lines += [
			"",
			"if [ -s $prefix/grubenv ]; then",
			"    load_env",
			"fi",
			"",
			"function savedefault {",
			"    if [ -z \"{boot_once}\" ]; then",
			"        saved_entry=\"${chosen}\"",
			"        save_env saved_entry",
			"    fi",
			"}"
		]
		
		if self.boot_config.hasItem("boot/terminal") and self.boot_config["boot/terminal"] == "serial":
			self.msgs.append(["warn", "Configured for SERIAL input/output."])
			boot_menu.lines += [
				"serial --unit=%s --speed=%s --word=%s --parity=%s --stop=%s" % (
					self.boot_config["serial/unit"],
					self.boot_config["serial/speed"],
					self.boot_config["serial/word"],
					self.boot_config["serial/parity"],
					self.boot_config["serial/stop"]),
				"terminal_input serial",
				"terminal_output serial"
			]
		elif self.boot_config.hasItem("display/gfxmode"):
			boot_menu.lines.append("")
			self.PrepareGRUBForFilesystem(os.path.join(self.config.root_path, self.boot_config["boot/path"].lstrip('/')), boot_menu.lines)
			if self.boot_config.hasItem("display/font"):
				font = self.boot_config["display/font"]
			else:
				font = None
			
			dst_font = None
			
			if font is None:
				fonts = ["unicode.pf2", "unifont.pf2"]
			else:
				fonts = [font]
			
			for fontpath in [self.grubpath, self.grubpath + "/fonts"]:
				if dst_font is not None:
					break
				for font in fonts:
					path_to_font = fontpath + "/" + font
					full_path_to_font = os.path.join(self.config.root_path, path_to_font.lstrip("/"))
					if os.path.exists(full_path_to_font):
						dst_font = path_to_font
						break
			
			if dst_font is None:
				# font does not exist at destination... so we will need to find it somewhere and copy into /boot/grub
				for fontpath in self.boot_config["grub/font_src"].split():
					if dst_font is not None:
						break
					for font in fonts:
						path_to_font = fontpath + "/" + font
						if os.path.exists(path_to_font):
							src_font = path_to_font
							dst_font = self.grubpath + '/fonts/' + font
							dst_font = os.path.join(self.config.root_path, dst_font.lstrip("/"))
							if not os.path.exists(dst_font):
								import shutil
								shutil.copy(src_font, dst_font)
							break
			
			if dst_font is None:
				if font:
					self.msgs.append(["fatal", "specified font \"{ft}\" not found at {dst}; aborting.".format(ft=font, dst=dst_font)])
				else:
					self.msgs.append(["fatal", "Could not find one of %s to copy into boot directory; aborting." % ",".join(fonts)])
				boot_menu.success = False

			
			boot_menu.lines += ["if loadfont {dst}; then".format(dst=self.resolver.RelativePathTo(dst_font, self.boot_config["boot/path"])),
				  "   set gfxmode={gfx}".format(gfx=self.sanitizeDisplayMode(self.boot_config["display/gfxmode"])),
				  "   insmod all_video",
				  "   terminal_output gfxterm"]
			bg = self.boot_config.item("display", "background").split()
			if len(bg):
				bgimg = None
				bgext = None
				if len(bg) == 1:
					# get extension from file:
					bgimg = bg[0]
					bgext = bg[0].rsplit(".")[-1].lower()
				elif len(bg) == 2:
					# extension specified as second argument:
					bgimg, bgext = bg
				else:
					self.msgs.append(["warn", "Unexpected number of arguments for background image - skipping."])
				if bgimg is not None:
					if bgext == "jpg":
						bgext = "jpeg"
					if bgext in ["jpeg", "png", "tga"]:
						rel_cfgpath = "{path}/{img}".format(path=self.boot_config["boot/path"], img=bgimg)
						
						# first, look for absolute path, because our relative path
						# can eval to "/boot/boot/foo.png" which
						# due to the /boot/boot symlink will "exist".
						
						if bgimg[0] == "/" and os.path.exists(bgimg):
							# user specified absolute path to file on disk:
							boot_menu.lines += [
								"   insmod {bg}".format(bg=bgext),
								"   background_image {img}".format(img=self.resolver.RelativePathTo(bgimg, self.boot_config["boot/path"]))
							]
						elif os.path.exists(rel_cfgpath):
							# user specified path relative to /boot:
							boot_menu.lines += [
								"   insmod {ext}".format(ext=bgext),
								"   background_image {img}".format(img=self.resolver.RelativePathTo(rel_cfgpath, self.boot_config["boot/path"]))
							]
						else:
							self.msgs.append(["warn", "background image \"{img}\" does not exist - skipping.".format(img=bgimg)])
					else:
						self.msgs.append(["warn", "background image \"{img}\" (format \"{ext}\") not recognized - skipping.".format(img=bgimg, ext=bgext)])
			boot_menu.lines += ["fi",
								"",
								self.boot_config.condFormatSubItem("color/normal", "set menu_color_normal={s}"),
								self.boot_config.condFormatSubItem("color/highlight", "set menu_color_highlight={s}"),
								]
		else:
			if self.boot_config.hasItem("display/background"):
				self.msgs.append(["warn", "display/gfxmode not provided - display/background \"{bg}\" will not be displayed.".format(bg=self.boot_config["display/background"])])
		self.resolver.GenerateSections(boot_menu, self.generateBootEntry, self.generateOtherBootEntry)
		
		if boot_menu.user_specified_attempt_identifier:
			if boot_menu.attempt_kname is not None and boot_menu.attempt_position is not None:
				boot_menu.lines += [

				]
				# This condition indicates that we successfully found the boot entry in the boot menu:
				# Record entry on-disk as a kernel to promote to default if we succeed booting...
				self.boot_config.idmapper.update_promote_kname(boot_menu._attempt_kname)
				self._attempt_kernel(boot_menu)
			else:
				self.msgs.append(["error", "Unable to find a matching boot entry for attempted kernel you specified."])
		else:
			# make sure the *default* kernel is attempted, to wipe out any existing attempt settings.
			self._attempt_kernel(boot_menu, set_default=True)
		
		# The following lines load the GRUB env data. Then we see if "$next_entry" is set, which specifies a to-be-attempted kernel.
		# If so, it becomes the default (for one boot.) Otherwise, we look and see if "$saved_entry" is set, which is the grub env
		# variable set by "grub-set-default". If this specifies a default kernel, we'll use it. Otherwise, fall back to a hard-
		# coded value from boot-update config itself, pointing to the default kernel.
		
		boot_menu.lines += [
			"",
			"if [ ! \"${next_entry}\" = \"\" ] ; then",
			"    set default=\"${next_entry}\"",
			"    set next_entry=",
			"    save_env next_entry",
			"    set boot_once=true",
			"elif [ ! \"${saved_entry}\" = \"\" ]; then",
			"    set default=\"${saved_entry}\"",
			"else",
			"    set default={pos}".format(pos=boot_menu.default_position),
			"fi"
		]
	
	def GuppyMap(self):
		""" Creates the device map """
		gmkdevmap = "/sbin/grub-mkdevicemap"
		if not os.path.exists(gmkdevmap):
			# grub-2.00 and above does not have mkdevicemap - so skip it if we don't see it.
			return
		cmdobj = None
		if self.testing:
			cmdstr = "{gm} --no-floppy --device-map=/dev/null".format(gm=gmkdevmap)
			cmdobj = Popen(cmdstr, bufsize=-1, stdout=PIPE, stderr=STDOUT, shell=True)
		else:
			cmdobj = Popen([gmkdevmap, "--no-floppy"], bufsize=-1, stdout=PIPE, stderr=STDOUT, shell=False)
		output = cmdobj.communicate()
		if cmdobj.poll() != 0:
			raise ExtensionError("{cmd}\n{out}".format(cmd=gmkdevmap, out=output[0].decode()))
	
	def Guppy(self, argstring, fatal=True):
		""" Probes a device """
		gprobe = self.grubProbe()
		cmd = shlex.split("{gcmd} {args}".format(gcmd=gprobe, args=argstring))
		cmdobj = Popen(cmd, bufsize=-1, stdout=PIPE, stderr=PIPE, shell=False)
		output = cmdobj.communicate()
		retval = cmdobj.poll()
		if fatal and retval != 0:
			raise ExtensionError("{cmd} {args}\n{out}".format(cmd=gprobe, args=argstring, out=output[0].decode()))
		else:
			return retval, output[0].decode().strip("\n")
	
	def RequiredGRUBModules(self, dev):
		""" Determines required grub modules """
		mods = []
		for targ in ["abstraction", "partmap", "fs"]:
			for mod in self.DeviceProbe(dev, targ):
				# grub-1.98 will return "part_gpt", while 2.00 will return "gpt" -- accommodate this:
				if targ == "partmap" and mod[:5] != "part_":
					mod = "part_" + mod
				mods.append(mod)
		return mods
	
	def DeviceProbe(self, dev, targ):
		""" Determines the device details """
		retval, mods = self.Guppy(" --device {d} --target={t}".format(d=dev, t=targ))
		if retval == 0:
			return mods.split()
		else:
			return []
	
	def DeviceOfFilesystem(self, fs):
		""" Determines the device of a filesystem """
		retval, out = self.Guppy(" --target=device {f}".format(f=fs))
		return retval, out
	
	def DeviceUUID(self, dev):
		""" Determines the UUID of the filesystem """
		retval, out = self.Guppy(" --device {d} --target=fs_uuid".format(d=dev))
		return retval, out
	
	def DeviceGRUB(self, dev):
		""" Determines the Grub device for a Linux device """
		retval, out = self.Guppy(" --device {d} --target=drive".format(d=dev))
		return retval, out
	
	def PrepareGRUBForFilesystem(self, fs, l):
		""" Prepares Grub for the filesystem """
		retval, dev = self.DeviceOfFilesystem(fs)
		return self.PrepareGRUBForDevice(dev, l)
	
	def PrepareGRUBForDevice(self, dev, l):
		""" Prepares Grub for the device """
		for mod in self.RequiredGRUBModules(dev):
			l.append("  insmod {m}".format(m=mod))
		retval, grubdev = self.DeviceGRUB(dev)
		l.append("  set root={dev}".format(dev=self.resolver.device_shift(grubdev)))
		retval, uuid = self.DeviceUUID(dev)
		if retval == 0:
			l.append("  search --no-floppy --fs-uuid --set {u}".format(u=uuid))
	# TODO: add error handling for retvals

# vim: ts=4 sw=4 noet
