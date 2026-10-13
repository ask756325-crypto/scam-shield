export const metadata = { title: "Terms of use" };

export default function TermsPage() {
  return (
    <>
      <h1>Terms of use</h1>
      <p className="text-[12.5px] text-ink-500">ScamShield AI is a prototype built for the byteXL HacXLerate Challenge 03. These terms describe the intended, acceptable use of the software.</p>

      <h2>What the service does</h2>
      <p>ScamShield AI helps an organization discover publicly visible accounts and app listings that may impersonate brands it is authorised to protect. It produces heuristic risk scores to prioritise human review.</p>

      <h2>Findings are not determinations</h2>
      <ul>
        <li>Risk scores and classifications are heuristic evidence, not calibrated probabilities, and do not establish that any account, app or person acted unlawfully or maliciously.</li>
        <li>Every finding requires review by a person before any action — such as a report or takedown request — is taken. The software does not file reports automatically.</li>
        <li>Coverage is limited to the sources listed on the Sources page. Absence of a finding does not mean absence of impersonation.</li>
      </ul>

      <h2>Acceptable use</h2>
      <ul>
        <li>Only monitor brands you own or are authorised to protect.</li>
        <li>Do not use the software to harass, profile or track individuals.</li>
        <li>Respect the terms and rate limits of each source platform. The software uses only public endpoints and does not bypass access controls; do not modify it to do so.</li>
        <li>Keep your credentials confidential. You are responsible for activity in your organization’s workspace.</li>
      </ul>

      <h2>Third-party sources</h2>
      <p>Source availability depends on third parties. The Google Play adapter relies on an unofficial open-source parser and may stop working without notice. Sources may rate-limit or reject requests; these outcomes are reported as-is.</p>

      <h2>No warranty</h2>
      <p>The software is provided “as is”, without warranty of any kind, express or implied, including fitness for a particular purpose. To the extent permitted by law, the authors are not liable for decisions made using its output.</p>
    </>
  );
}
