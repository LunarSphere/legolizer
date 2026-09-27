import React from 'react';
import { X } from 'lucide-react';

export default function ErrorAlert({ children, onDismiss, className = 'form-error' }) {
  return <div className={className} role="alert">
    <button type="button" className="error-dismiss" onClick={onDismiss} aria-label="Dismiss error"><X size={14} /></button>
    {children}
  </div>;
}
