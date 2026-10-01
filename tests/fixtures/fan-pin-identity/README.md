# Official fan pin identity inputs

These are unmodified upstream Klipper files at
`fe4eb8650bd7de4c2100a14eaf09b0965c430e29` (GPL-3.0):

| File | SHA-256 |
|---|---|
| generic-replicape.cfg | `233c46fc2a5f97d975fcbebd25c32ff1a14020a5346b3c970cdf639465430bca` |
| printer-geeetech-301-2019.cfg | `695177103bfdcc10b8d0bad6a14d0c7bfea4dee3f28d1771994a3d3147588ebe` |

Source: https://github.com/Klipper3d/klipper/tree/fe4eb8650bd7de4c2100a14eaf09b0965c430e29/config

They reproduce K22's virtual-chip namespaces during discovery. They are not
generated snapshots or a claim of full KACE support for these printer models.
The inverted `!toolhead:gpio5` case is a separate synthetic regression.
