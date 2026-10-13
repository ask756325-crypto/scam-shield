export const metadata = { title: "Privacy notice" };

export default function PrivacyPage() {
  return (
    <>
      <h1>Privacy notice</h1>
      <p className="text-[12.5px] text-ink-500">Applies to this ScamShield AI deployment. It describes how the software behaves; the operator of a deployment is responsible for its own legal obligations.</p>

      <h2>Account data</h2>
      <ul>
        <li>We store your name, email address, organization name and a password hash (Argon2id). Plain-text passwords are never stored or logged.</li>
        <li>Sessions use a random token in an HttpOnly cookie; only a SHA-256 hash of the token is stored server-side. By default the cookie lasts until the browser closes and the session expires after 12 hours; with “Keep me signed in” it lasts 30 days. Sign-out revokes the session immediately.</li>
        <li>Password-reset tokens are single-use, stored hashed, and expire after 30 minutes.</li>
      </ul>

      <h2>Brand data you provide</h2>
      <p>Brand profiles (names, domains, official accounts and apps, keywords, descriptions) and uploaded logos are stored to run scans. Logos are re-encoded as PNG to strip metadata. Only members of your organization can access them.</p>

      <h2>Data collected from public sources</h2>
      <ul>
        <li>Scans query public, unauthenticated endpoints of Bluesky, Mastodon instances you configure, the Apple iTunes Search API and public Google Play listing pages.</li>
        <li>Collected profiles and listings that do not meet the brand-relevance threshold are counted but <strong>not retained</strong>.</li>
        <li>Retained candidates store the public profile/listing fields needed as evidence: name, handle, URL, description, avatar/icon URL, publisher, links and source metadata, plus observation timestamps.</li>
        <li>Avatar and icon images are fetched only from an allowlist of known media hosts, hashed in memory for logo comparison, and not stored.</li>
        <li>Links found in profiles are analysed as text and are never visited by the server.</li>
      </ul>

      <h2>Retention</h2>
      <p>Data is kept until you delete it. Deleting a brand permanently removes its scans, candidates, findings, decisions and exclusion records. Deleting the database removes everything. There is no automatic expiry in this version; operators should define a retention period appropriate to their use.</p>

      <h2>Sharing</h2>
      <p>The software does not send your data to third parties, analytics services or advertisers. Outbound requests are limited to the public source endpoints listed above and, if configured by the operator, an SMTP server for password-reset email.</p>

      <h2>Certifications</h2>
      <p>This software has not been audited or certified against any compliance framework (such as SOC 2, ISO 27001 or GDPR certification schemes), and makes no such claim.</p>
    </>
  );
}
