# Transfer DNS from TransIP to mijn.host

The helper exports TransIP DNS over its v6 API, generates a BIND-style zonefile for the mijn.host control panel, and compares published records with the export. Use Python 3.9+ and `dig`. The helper's only provider API operation is a read from TransIP.

1. Save a TransIP v6 bearer token in a private file, then export the zone and generate the template input.

   ```sh
   umask 077
   export TRANSIP_TOKEN_FILE=/path/to/private/transip-token
   python3 migration/dns_migrate.py export example.net example.net-source.json
   python3 migration/dns_migrate.py zonefile example.net-source.json example.net.zone
   ```

   The export contains your live DNS data. Store it and the generated zonefile privately. Review the result before import, including MX priorities, SPF, DKIM, DMARC, CAA and TLSA. The script leaves SOA, apex NS and generated DNSSEC records to the provider. It stops on unsupported record types.

2. In **Mijn DNS templates**, create a template and use **Zonefile bewerken** to paste the generated zonefile. Verify that the panel preserves all records, including TLSA and CAA. Select the matching template at checkout if transferring the registrar as well. Retrieve the transfer code separately and enter it only in the provider's checkout. [mijn.host template instructions](https://mijn.host/kb/domeinnaam/dns-templates)

3. Coordinate the DNSSEC handoff before changing nameservers. The parent DS needs to match keys served by the new authority. If the providers require a temporary unsigned period, account for cached DS records and the impact on DANE before proceeding. [TransIP DNSSEC transfer guidance](https://www.transip.nl/knowledgebase/152-domeinnaam-dnssec-verhuizen-andere-provider)

4. Compare the new authority against the export. This checks expected record values, including all values in each exported RRset. It does not audit TTLs or detect records at names absent from the export.

   ```sh
   python3 migration/dns_migrate.py check example.net-source.json \
     --server ns1.mijn.host --server ns2.mijn.host --server ns3.mijn.host
   ```

5. Check the parent delegation directly and compare it with a validating resolver. For a `.nl` domain:

   ```sh
   dig @ns1.dns.nl example.nl NS +norecurse +noall +authority
   dig @ns1.dns.nl example.nl DS +norecurse +noall +answer
   dig @1.1.1.1 example.nl SOA +dnssec
   ```

   WHOIS can show the new registrar and nameservers before the parent DNS publishes the new delegation. Confirm the actual parent delegation and, for a signed zone, the `ad` flag on a validating resolver's answer. Test web and mail before retiring the old zone. Then follow the [Certbot guide](../README.md) to switch DNS-01 renewals.
