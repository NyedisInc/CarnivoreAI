carnivore crate, format 1

this file is a crate: one archive that holds conversations, their files and database rows, written by carnivore.
the format is described in docs/crate-format.md in the carnivore source. it is a plain uncompressed tar file.

to look inside with no carnivore installed:

  tar -tf x.crate                  lists every member
  tar -xf x.crate                  unpacks it into the current folder
  zstd -d blobs/ab/<sha>.zst -o chunk   restores one chunk (blobs ending .xz: xz -d)

files.jsonl lists every file, one json object per line. each file's "chunks" are [sha256, length] pairs in order;
concatenating those chunks rebuilds the file byte for byte, and "content_sha256" is its sha256.

  python3 extract.py x.crate out/  rebuilds every file into the empty folder out/ and checks each hash
                                   (extract.py is a member of this crate; take it out with tar -xf x.crate extract.py)

rows/<store>/<table>.jsonl holds database rows, one json object per line; rows/schema.json describes the columns.
crate.json describes the whole crate and lists every member's sha256.

an encrypted crate (x.crate.age) is a standard age file. open it first:

  age -d -i <identity file> x.crate.age > x.crate
