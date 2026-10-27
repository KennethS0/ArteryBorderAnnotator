// main.js — Punto de entrada.
import { iniciarApp } from "./app.js";
import { crearAlmacenLocal } from "./almacen-local.js";

iniciarApp(crearAlmacenLocal());
