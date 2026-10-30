/* SPDX-License-Identifier: GPL-2.0-only
 * Exact excerpt from fstools e8cd820cdbb8fba990fd79efda90c5dc10d8e45c block.c.
 * Copyright (C) 2013 Felix Fietkau, John Crispin.
 */
/**
 * Look for extroot config and mount it if present
 *
 * Look for /etc/config/fstab on all supported partitions and use it for
 * mounting extroot if specified.
 */
static int main_extroot(int argc, char **argv)
{
	struct probe_info *pr;
	char blkdev_path[32] = { 0 };
	int err = -1;
#ifdef UBIFS_EXTROOT
	libubi_t libubi;
#endif

	if (!getenv("PREINIT"))
		return -1;

	if (argc != 2) {
		ULOG_ERR("Usage: block extroot\n");
		return -1;
	}

	make_devs();
	cache_load(1);

	/* enable LOG_INFO messages */
	ulog_threshold(LOG_INFO);

	/* try the currently mounted overlay if exists */
	err = mount_extroot("/tmp/overlay");
	if (!err)
	    return err;

	/*
	 * Look for "rootfs_data". We will want to mount it and check for
	 * extroot configuration.
	 */

	/* Start with looking for MTD partition */
	find_block_mtd("\"rootfs_data\"", blkdev_path, sizeof(blkdev_path));
	if (blkdev_path[0]) {
		pr = find_block_info(NULL, NULL, blkdev_path);
		if (pr && !strcmp(pr->type, "jffs2")) {
			char cfg[] = "/tmp/jffs_cfg";

			/*
			 * Mount MTD part and try extroot (using
			 * /etc/config/fstab from that partition)
			 */
			mkdir_p(cfg, 0755);
			if (!mount(blkdev_path, cfg, "jffs2", MS_NOATIME, NULL)) {
				err = mount_extroot(cfg);
				umount2(cfg, MNT_DETACH);
			}
			if (err < 0)
				rmdir("/tmp/overlay");
			rmdir(cfg);
			return err;
		}
	}

#ifdef UBIFS_EXTROOT
	/* ... but it also could be an UBI volume */
	memset(blkdev_path, 0, sizeof(blkdev_path));
	libubi = libubi_open();
	find_block_ubi(libubi, "rootfs_data", blkdev_path, sizeof(blkdev_path));
	libubi_close(libubi);
	if (blkdev_path[0]) {
		char cfg[] = "/tmp/ubifs_cfg";

		/* Mount volume and try extroot (using fstab from that vol) */
		mkdir_p(cfg, 0755);
		if (!mount(blkdev_path, cfg, "ubifs", MS_NOATIME, NULL)) {
			err = mount_extroot(cfg);
			umount2(cfg, MNT_DETACH);
		}
		if (err < 0)
			rmdir("/tmp/overlay");
		rmdir(cfg);
		return err;
       }
#endif

	/* As a last resort look for /etc/config/fstab on "rootfs" partition */
	return mount_extroot(NULL);
}
