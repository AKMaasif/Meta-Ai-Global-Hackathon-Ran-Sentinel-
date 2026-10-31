# Sample field evidence

Test files for the Field evidence card. When an investigation pauses and asks the field for something, open the folder that
matches the request and drop its files on the card. Each file is read as it is attached; then press Send and resume.

The photos are drawn illustrations with a caption bar, made for testing; they are not real site photos. The reports and
readings are made up but consistent with each fault.

| Folder | Matches a request like | Demo problem to create | Files |
|---|---|---|---|
| `overshoot_coverage` | "Photograph the antenna from the side ... confirm the RET setting" | Overshoot (tilt mis-set) on SEA-RAN-004 | side-view photo, RET readback CSV, site visit DOCX, notes TXT |
| `external_interference` | "Sweep the uplink with a spectrum analyser ..." | External interference on SEA-RAN-001 | booster photo, uplink sweep CSV, sweep report PDF, notes TXT |
| `hardware_fault` | "Photograph the antenna, feeder cable and connectors, and read VSWR" | Hardware fault (VSWR) on SEA-RAN-015 | connector photo, VSWR CSV, site visit DOCX, notes TXT |
| `capacity_surge` | "Report whether there is an event, crowd or new building ..." | Capacity surge (event crowd) on SEA-RAN-001 | stadium crowd photo, crowd count CSV, event notice TXT |
| `should_be_refused` | any | any | a scanned PDF with no text, an empty TXT and an XLSX: each is refused with a reason |

To make the investigation pause, turn on **Diagnostics outage** in Demo controls before creating the problem.

Try a mismatch too: attach the interference files to an overshoot request. The analyst should mark them as not fitting the
diagnosis.

The same files work with the live check: `py scripts\check_field_files.py --file samples\field_evidence\hardware_fault\vswr_readings.csv`
