# External Storage (automatic mounting)

## Initial Setup
Create mount point:
```
sudo mkdir -p /data/media/1
```
Format storage device:
```
sudo mkfs.ext4 /dev/sdg1
```
sudo nano /etc/systemd/system/usb-mount@.service
```
[Unit]
Description=Mount USB Drive
After=dev-%i.device

[Service]
Type=oneshot
ExecStart=/bin/mount /dev/%I /data/media/1
ExecStop=/bin/umount /data/media/1
RemainAfterExit=true

[Install]
WantedBy=multi-user.target
```
sudo nano /etc/udev/rules.d/99-usb-automount.rules
```
SUBSYSTEM=="block", KERNEL=="sdg1", ACTION=="add", TAG+="systemd", ENV{SYSTEMD_WANTS}="usb-mount@%k.service"
SUBSYSTEM=="block", KERNEL=="sdg1", ACTION=="remove", RUN+="/bin/systemctl stop usb-mount@%k.service"
```

Set permissions:
```
sudo udevadm control --reload-rules
sudo udevadm trigger
sudo systemctl daemon-reload
sudo systemctl enable usb-mount@sdg1.service
sudo chown -R comma:comma /data/media/1/
```


# External Storage (manual mounting)

## Initial Setup
Create mount point:
```
sudo mkdir -p /data/media/1
```
Format storage device:
```
sudo mkfs.ext4 /dev/sdg1
```
Mount storage device:
```
sudo mount /dev/sdg1 /data/media/1
```
Create realdata folder:
```
sudo mkdir /data/media/1/realdata
```
Set permissions:
```
sudo chown -R comma:comma /data/media/1/
```


## To Mount
Mount storage device:
```
sudo mount /dev/sdg1 /data/media/1
```


## To Unmount
Unmount storage device:
```
sudo umount /dev/sdg1
```