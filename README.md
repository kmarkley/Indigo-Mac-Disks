# Mac Disks

This plugin uses shell commands (`diskutil` and `df`) to determine if volumes are mounted on the machine running Indigo Server and obtain some statistics about them.  Volumes may be mounted or unmounted by turning the associated Indigo device on or off.

## Plugin Configuration

* **Update Frequency**  
How often to check whether disks have been mounted or unmounted.

* **Touch Disk Frequency**  
For disks that have been configured to prevent sleep, this determines how often to touch a hidden file.

* **Reset Identifier Frequency**  
For Local Disks, the logical attchment point (e.g. `disk1s2`) can occaisionally change between mounts.  This setting determines how often to confirm/reset the prior value.

* **Enable Debugging**  
If checked, extensive debug information will be written to the log.

## Device Configuration

### Local Disk

* **Volume Name**  
The name of the disk as it appears in the Finder.

* **Prevent Disk Sleep**  
Check to periodically touch a hidden file on the disk, thus preventing it from sleeping.

* **Force Unmount**  
Use the forced version of the unmount command.  This will unmount the disk even if there are open files.

### Network Disk

* **Volume Name**  
The name of the disk as it appears in the Finder.

* **Volume URL**  
The full URL used to connect to the network share.  Embed 'username:password@' for shares that require authentication.  Supported formats are smb, nfs, afp, ftp, and webdav.

* **Prevent Disk Sleep**  
Check to periodically touch a hidden file on the disk, thus preventing it from sleeping.

* **Force Unmount**  
Use the forced version of the unmount command.  This will unmount the disk even if there are open files.

## Device States

* **Total Size**  
Size of the disk as a string.

* **Total Megabytes**  
Size of the disk as an integer in megabytes.

* **Used Size**  
Used space on the disk as a string.

* **Used Megabytes**  
Used space on the disk as an integer in megabytes.

* **Free Size**  
Free space on the disk as a string.

* **Free Megabytes**  
Free space on the disk as an integer in megabytes.

* **Percent Used**  
Used space on the disk as a percent ot total.

* **Percent Free**  
Free space on the disk as a percent ot total.

* **Identifier**  
The identifier of the disk as it appaers in the first column of the `df` command.

* **Disk Type**  
The type of disk.

* **Last Touch**  
Timestamp of the last time the disk was touched to prevent sleep.


