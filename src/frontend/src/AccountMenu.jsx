import React, { useEffect, useRef, useState } from 'react';
import { LogOut } from 'lucide-react';

let identity = null;
let deliver = () => {};

function loadGoogle(clientId) {
  identity ??= new Promise((resolve, reject) => {
    const script = document.createElement('script');
    script.src = 'https://accounts.google.com/gsi/client';
    script.async = true;
    script.onload = () => {
      window.google.accounts.id.initialize({ client_id: clientId, callback: response => deliver(response.credential), cancel_on_tap_outside: true });
      resolve(window.google.accounts.id);
    };
    script.onerror = () => {
      identity = null;
      reject(new Error('Google sign-in could not load. Check your connection and try again.'));
    };
    document.head.append(script);
  });
  return identity;
}

export function forgetGoogleSelection() {
  window.google?.accounts.id.disableAutoSelect();
}

export function GoogleButton({ clientId, onCredential, size = 'large' }) {
  const target = useRef(null);
  const [error, setError] = useState('');
  useEffect(() => { deliver = onCredential; }, [onCredential]);
  useEffect(() => {
    let cancelled = false;
    loadGoogle(clientId)
      .then(id => { if (!cancelled && target.current) id.renderButton(target.current, { theme: 'outline', size, shape: 'pill', text: 'signin_with' }); })
      .catch(failure => { if (!cancelled) setError(failure.message); });
    return () => { cancelled = true; };
  }, [clientId, size]);
  return error ? <p className="form-error" role="alert">{error}</p> : <div className="google-button" ref={target} />;
}

export default function AccountMenu({ session, onSignIn, onSignOut }) {
  if (session?.auth !== 'google') return <span className="avatar">L</span>;
  if (!session.user) return session.googleClientId ? <GoogleButton clientId={session.googleClientId} onCredential={onSignIn} size="medium" /> : null;
  const { name, picture } = session.user;
  return <div className="account-chip">
    {picture ? <img className="account-avatar" src={picture} alt="" referrerPolicy="no-referrer" /> : <span className="account-avatar" aria-hidden="true">{name.slice(0, 1).toUpperCase()}</span>}
    <span className="account-name">{name}</span>
    <button type="button" className="icon-button" onClick={onSignOut} title="Sign out" aria-label={`Sign out ${name}`}><LogOut size={15} /></button>
  </div>;
}
