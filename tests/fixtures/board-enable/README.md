# Kobra Go board enable

`printer-anycubic-kobra-go-2022.cfg` is copied byte-for-byte from official Klipper
`fe4eb8650bd7de4c2100a14eaf09b0965c430e29`. The same bytes occur in archived
`ce7002bedf37e938bb483572949f3703ac6476cb`; hashes are recorded by K19-B10.

The source identifies PB6 as enabling the bed, hotend, extruder fan and part fan.
Tests use explicit fixture geometry 220x220x250 and the original probe definition.
They verify configuration preservation, not physical thermal/firmware behavior.
